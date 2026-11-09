"""Gmail send-only integration. Refresh tokens encrypted; no Sent Mail reads."""
import base64, hashlib, html, json, secrets
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from urllib.parse import urlencode
import httpx
from cryptography.fernet import Fernet
from .common import now,maybe,all_rows
from ..errors import AppError

SCOPE='https://www.googleapis.com/auth/gmail.send'

class Gmail:
    def __init__(self,ctx,transport=None):
        self.ctx,self.s,self.repo,self.transport=ctx,ctx.settings,ctx.repository,transport
    def cipher(self):
        try:return Fernet(self.s.gmail_token_encryption_key.get_secret_value().encode())
        except Exception:raise AppError('GMAIL_CONFIG','Set a valid GMAIL_TOKEN_ENCRYPTION_KEY (Fernet key)',503)
    def configured(self):
        return bool(self.s.gmail_client_id and self.s.gmail_client_secret.get_secret_value() and self.s.gmail_token_encryption_key.get_secret_value())
    def connection(self,conn):
        return maybe(self.repo,conn,'gmail','sender',{})
    def status(self):
        with self.repo.engine.connect() as conn:r=self.connection(conn)
        return {'configured':self.configured(),'connected':bool(r.get('encrypted_tokens')) and not r.get('reconnect_required',False),'sender':r.get('email'),
                'send_enabled':self.s.email_send_enabled and self.s.app_env=='production','reconnect_required':r.get('reconnect_required',False)}
    def start(self,browser_nonce):
        if not self.configured():raise AppError('GMAIL_CONFIG','Configure Gmail OAuth client, redirect URI and encryption key',503)
        self.cipher()
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        self.repo.put('gmail_oauth',hashlib.sha256(state.encode()).hexdigest(),{'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),
            'browser_hash':hashlib.sha256(browser_nonce.encode()).hexdigest(),'verifier':self.cipher().encrypt(verifier.encode()).decode(),'used':False})
        return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':self.s.gmail_client_id,'redirect_uri':self.s.gmail_redirect_uri,'response_type':'code',
            'scope':SCOPE+' openid email','access_type':'offline','prompt':'consent','state':state,'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),'code_challenge_method':'S256'})
    async def callback(self,state,code,browser_nonce):
        with self.repo.transaction() as conn:
            key=hashlib.sha256(state.encode()).hexdigest();r=maybe(self.repo,conn,'gmail_oauth',key)
            if not r or r['used'] or datetime.fromisoformat(r['expires_at'])<=datetime.now(timezone.utc) or not secrets.compare_digest(r['browser_hash'],hashlib.sha256(browser_nonce.encode()).hexdigest()):
                raise AppError('OAUTH_STATE','Gmail connection expired or belongs to another browser; reconnect',403)
            r['used']=True;self.repo._put(conn,'gmail_oauth',key,r)
        async with httpx.AsyncClient(timeout=20,transport=self.transport) as c:
            response=await c.post('https://oauth2.googleapis.com/token',data={'client_id':self.s.gmail_client_id,'client_secret':self.s.gmail_client_secret.get_secret_value(),'redirect_uri':self.s.gmail_redirect_uri,'grant_type':'authorization_code','code':code,'code_verifier':self.cipher().decrypt(r['verifier'].encode()).decode()})
            if response.status_code!=200:raise AppError('GMAIL_AUTH','Google authorization failed; reconnect Gmail',502)
            tokens=response.json()
            if SCOPE not in tokens.get('scope','').split():
                raise AppError('GMAIL_SCOPE','Gmail sending permission was not granted. Start Connect Gmail again and select the permission to send email on your behalf on the Google consent screen.',403)
            if not tokens.get('refresh_token'):
                raise AppError('GMAIL_OFFLINE_ACCESS','Google did not return offline authorization. Remove TalentBridge AI from your Google Account third-party connections, then start Connect Gmail again and grant Gmail sending permission.',403)
            who=await c.get('https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+tokens['access_token']})
            if who.status_code!=200 or not who.json().get('email_verified'):raise AppError('GMAIL_IDENTITY','Cannot verify sender identity',403)
        from pydantic import TypeAdapter,EmailStr
        email=str(TypeAdapter(EmailStr).validate_python(who.json()['email']))
        with self.repo.transaction() as conn:
            if any(m['state'] in ('SENDING','DELIVERY_UNKNOWN') for m in all_rows(self.repo,conn,'hr_outbox')):
                raise AppError('EMAIL_UNRESOLVED','Reconcile the in-flight or uncertain send before changing Gmail accounts',409)
            self.repo._put(conn,'gmail','sender',{'email':email,'subject':who.json()['sub'],'connected_at':now(),'reconnect_required':False,
                'encrypted_tokens':self.cipher().encrypt(json.dumps({'refresh_token':tokens['refresh_token']}).encode()).decode()})
        return email
    async def access_token(self,sender):
        with self.repo.engine.connect() as conn:r=self.connection(conn)
        if not r.get('encrypted_tokens') or r.get('reconnect_required') or r.get('email')!=sender:raise AppError('GMAIL_AUTH','Reconnect the reviewed Gmail sender account',409)
        try:refresh=json.loads(self.cipher().decrypt(r['encrypted_tokens'].encode()))['refresh_token']
        except Exception:raise AppError('GMAIL_AUTH','Stored Gmail authorization cannot be decrypted; reconnect',409)
        async with httpx.AsyncClient(timeout=20,transport=self.transport) as c:
            try:response=await c.post('https://oauth2.googleapis.com/token',data={'client_id':self.s.gmail_client_id,'client_secret':self.s.gmail_client_secret.get_secret_value(),'grant_type':'refresh_token','refresh_token':refresh})
            except httpx.HTTPError:raise AppError('GMAIL_AUTH_TEMPORARY','Google token service unavailable; retry this email later',503,True)
        if response.status_code!=200:
            if response.status_code in (400,401):
                r['reconnect_required']=True;self.repo.put('gmail','sender',r)
            raise AppError('GMAIL_AUTH','Refresh failed; reconnect Gmail before retrying this email',409)
        return response.json()['access_token']
    async def send(self,message,attachment):
        if not self.s.email_send_enabled or self.s.app_env!='production':raise AppError('SENDING_DISABLED','Real sending is disabled outside production',409)
        token=await self.access_token(message['sender'])
        mime=EmailMessage();mime['From']=message['sender'];mime['To']=message['to'];mime['Subject']=message['subject']
        mime['Message-ID']='<'+hashlib.sha256(message['key'].encode()).hexdigest()+'@talentbridge.local>'
        mime.set_content(message['body']);mime.add_alternative('<html><body>'+''.join('<p>'+html.escape(p).replace('\n','<br>')+'</p>' for p in message['body'].split('\n\n'))+'</body></html>',subtype='html')
        if attachment:
            mime.add_attachment(base64.b64decode(attachment['content']),maintype='application',subtype='octet-stream',filename=attachment['filename'])
        raw=base64.urlsafe_b64encode(mime.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30,transport=self.transport) as c:
            try:response=await c.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',headers={'Authorization':'Bearer '+token},json={'raw':raw})
            except httpx.HTTPError:raise AppError('DELIVERY_UNKNOWN','Gmail may have accepted this send. Check Sent Mail manually before reconciliation.',409)
        if response.status_code>=500:raise AppError('DELIVERY_UNKNOWN','Gmail returned a server error; inspect Sent Mail before reconciliation',409)
        if response.status_code==429:raise AppError('GMAIL_QUOTA','Gmail rate or sending limit reached; wait before retrying',429,True)
        if response.status_code in (401,403):raise AppError('GMAIL_AUTH_OR_QUOTA','Check Gmail authorization, account sending limits and API quota',409)
        if response.status_code!=200:raise AppError('GMAIL_REJECTED','Gmail rejected the message; check attachment and recipients',422)
        try:message_id=response.json()['id']
        except (ValueError,KeyError):raise AppError('DELIVERY_UNKNOWN','Gmail response lacked a message ID; reconcile before retry',409)
        if not isinstance(message_id,str) or not message_id.strip():raise AppError('DELIVERY_UNKNOWN','Gmail returned an invalid message ID; reconcile before retry',409)
        return message_id
