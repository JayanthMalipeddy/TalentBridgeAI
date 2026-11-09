"""Durable, paced outbox. Uncertain sends never retry automatically."""
from datetime import datetime,timezone,timedelta
from .common import now,maybe,all_rows
from .service import HRService
from .gmail import Gmail
from ..errors import AppError

async def process_one(ctx,sender=None):
    # Tests inject an explicit fake sender; the application never does.
    if sender is None and (not ctx.settings.email_send_enabled or ctx.settings.app_env!='production'):return None
    repo=ctx.repository;hr=HRService(ctx);clock=datetime.now(timezone.utc)
    with repo.transaction() as c:
        rows=all_rows(repo,c,'hr_outbox')
        for row in rows:
            if row['state']=='SENDING':
                if (clock-datetime.fromisoformat(row['started_at'])).total_seconds()>ctx.settings.email_send_lease_seconds:
                    row.update(state='DELIVERY_UNKNOWN',error='Worker stopped before recording the provider response; reconcile manually')
                    repo._put(c,'hr_outbox',row['key'],row)
                else:return None
        pace=maybe(repo,c,'hr_mail_clock','global',{})
        if pace and (clock-datetime.fromisoformat(pace['last_attempt'])).total_seconds()<ctx.settings.email_pacing_seconds:return None
        attempts=[a for r in rows for a in r['attempts'] if datetime.fromisoformat(a['started_at']).date()==clock.date()]
        if len(attempts)>=ctx.settings.email_daily_cap:return None
        row=next((r for r in sorted(rows,key=lambda x:x['created_at']) if r['state']=='QUEUED' and not r.get('cancelled')),None)
        if not row:return None
        decision=repo._get(c,'hr_decision',row['case_id'])
        preview=hr._preview(c,row['case_id'])
        if decision['version']!=row['decision_version'] or preview['preview_version']!=decision['preview_version']:
            row.update(state='FAILED',error='REVIEW_CHANGED',cancelled=True);repo._put(c,'hr_outbox',row['key'],row);return row
        if row['purpose']=='candidate':
            prior=repo._get(c,'hr_outbox',row['case_id']+':'+row['decision_version']+':client')
            if prior['state']!='SEND_ACCEPTED':return None
        attachment=repo._get(c,'hr_cv',row['case_id']) if row['purpose']=='client' else None
        if attachment and attachment['sha256']!=decision['approved_snapshot']['cv']['sha256']:raise AppError('CV_CHANGED','CV changed since review',409)
        row.update(state='SENDING',started_at=now());row['attempts'].append({'started_at':row['started_at'],'state':'SENDING'})
        repo._put(c,'hr_outbox',row['key'],row);repo._put(c,'hr_mail_clock','global',{'last_attempt':row['started_at']})
    message_id=None
    try:
        message_id=await (sender or Gmail(ctx)).send(row,attachment)
        if not message_id:raise AppError('DELIVERY_UNKNOWN','Provider returned no message ID',409)
        state,error='SEND_ACCEPTED',None
    except AppError as e:state,error=('DELIVERY_UNKNOWN' if e.code=='DELIVERY_UNKNOWN' else 'FAILED'),e.code
    except Exception:state,error='DELIVERY_UNKNOWN','UNEXPECTED_SEND_FAILURE'
    with repo.transaction() as c:
        row=repo._get(c,'hr_outbox',row['key'])
        row.update(state=state,error=error,provider_message_id=message_id,finished_at=now())
        row['attempts'][-1].update(state=state,error=error,provider_message_id=message_id,finished_at=row['finished_at'])
        repo._put(c,'hr_outbox',row['key'],row)
        if state=='SEND_ACCEPTED' and row['purpose']=='client':hr._queue(c,repo._get(c,'hr_decision_version',row['decision_version']),'candidate')
    return row

def retry(ctx,cid,key):
    with ctx.repository.transaction() as c:
        r=ctx.repository._get(c,'hr_outbox',key)
        if r['case_id']!=cid:raise AppError('NOT_FOUND','Message not found',404)
        if r['state']!='FAILED' or r.get('cancelled') or len(r['attempts'])>=ctx.settings.email_max_attempts:raise AppError('EMAIL_RETRY_BLOCKED','Only a failed, current message within its attempt limit may be retried; uncertain sends require reconciliation',409)
        r.update(state='QUEUED',error=None);ctx.repository._put(c,'hr_outbox',key,r);return r

def reconcile(ctx,cid,key,body,reviewer):
    repo=ctx.repository
    with repo.transaction() as c:
        r=repo._get(c,'hr_outbox',key)
        if r['case_id']!=cid:raise AppError('NOT_FOUND','Message not found',404)
        if r['state']!='DELIVERY_UNKNOWN':raise AppError('EMAIL_RECONCILE','Only uncertain sends need reconciliation',409)
        if body.action=='confirmed_sent' and not body.provider_message_id:raise AppError('MESSAGE_ID_REQUIRED','Record the Gmail message ID verified manually',422)
        r.update(state='SEND_ACCEPTED' if body.action=='confirmed_sent' else 'FAILED',provider_message_id=body.provider_message_id,error=None if body.action=='confirmed_sent' else 'MANUALLY_CONFIRMED_NOT_SENT')
        r.setdefault('reconciliations',[]).append({'reviewer':reviewer,'at':now(),**body.model_dump()})
        repo._put(c,'hr_outbox',key,r)
        if r['state']=='SEND_ACCEPTED' and r['purpose']=='client':HRService(ctx)._queue(c,repo._get(c,'hr_decision_version',r['decision_version']),'candidate')
        return r
