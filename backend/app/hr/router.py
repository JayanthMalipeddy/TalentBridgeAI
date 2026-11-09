"""HR routes require BOTH case ownership and server recruiter authorization."""
import hashlib,secrets
from fastapi import APIRouter,Depends,Request,Response,UploadFile,File
from fastapi.responses import RedirectResponse
from .contracts import Configuration,Rubric,Decision,Correction,Reconcile,TranscriptCorrection
from .service import HRService
from .gmail import Gmail
from . import outbox
from ..auth import recruiter
from ..guest import owned_case
from ..errors import AppError

router=APIRouter()
def operator(request:Request):
    token=request.headers.get('x-recruiter-token','')
    recruiter(request,'Bearer '+token)
    return 'recruiter-token:'+hashlib.sha256(token.encode()).hexdigest()[:16]
def ctx(request):return request.app.state.ctx

@router.get('/gmail/status',dependencies=[Depends(operator)])
def gmail_status(request:Request):return Gmail(ctx(request)).status()

@router.post('/gmail/connect',dependencies=[Depends(operator)])
def gmail_connect(request:Request,response:Response):
    nonce=secrets.token_urlsafe(32)
    url=Gmail(ctx(request)).start(nonce)
    response.set_cookie('tb_gmail_oauth',nonce,httponly=True,secure=ctx(request).settings.app_env=='production',samesite='lax',max_age=600,path='/api/hr/gmail/callback')
    return {'url':url}

@router.get('/gmail/callback')
async def gmail_callback(request:Request,state:str='',code:str='',error:str=''):
    if error or not code:raise AppError('GMAIL_AUTH','Gmail connection cancelled; return to HR review and reconnect',400)
    await Gmail(ctx(request)).callback(state,code,request.cookies.get('tb_gmail_oauth',''))
    response=RedirectResponse(ctx(request).settings.frontend_origin.split(',')[0].rstrip('/')+'/app/reports',status_code=303)
    response.delete_cookie('tb_gmail_oauth',path='/api/hr/gmail/callback');return response

case_router=APIRouter(prefix='/cases/{case_id}',dependencies=[Depends(owned_case),Depends(operator)])
@case_router.get('/review')
def review(case_id:str,request:Request):return HRService(ctx(request)).preview(case_id)
@case_router.post('/prepare')
async def prepare(case_id:str,request:Request):return await HRService(ctx(request)).prepare(case_id)
@case_router.post('/configuration')
def configure(case_id:str,body:Configuration,request:Request):return HRService(ctx(request)).configure(case_id,body)
@case_router.post('/ready')
def ready(case_id:str,request:Request):return HRService(ctx(request)).mark_ready(case_id)
@case_router.post('/cv')
async def cv(case_id:str,request:Request,cv_file:UploadFile=File(...)):
    content=await cv_file.read(ctx(request).settings.max_cv_bytes+1)
    return HRService(ctx(request)).attachment(case_id,cv_file.filename or '',content)
@case_router.get('/cv')
def download_cv(case_id:str,request:Request):
    import base64
    from urllib.parse import quote
    value=ctx(request).repository.get('hr_cv',case_id)
    return Response(base64.b64decode(value['content']),media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(value['filename']),'Cache-Control':'no-store'})
@case_router.post('/rubric')
def rubric(case_id:str,body:Rubric,request:Request):return HRService(ctx(request)).rubric(case_id,body)
@case_router.post('/assess')
async def assess(case_id:str,request:Request,retry:bool=False):return await HRService(ctx(request)).assess(case_id,retry)
@case_router.post('/correction')
def correction(case_id:str,body:Correction,request:Request):return HRService(ctx(request)).correct(case_id,body)
@case_router.post('/decision')
def decision(case_id:str,body:Decision,request:Request):return HRService(ctx(request)).decide(case_id,body,operator(request))
@case_router.post('/emails/{key}/retry')
def retry(case_id:str,key:str,request:Request):return outbox.retry(ctx(request),case_id,key)
@case_router.post('/emails/{key}/reconcile')
def reconcile(case_id:str,key:str,body:Reconcile,request:Request):return outbox.reconcile(ctx(request),case_id,key,body,operator(request))
router.include_router(case_router)


@router.post('/cases/{case_id}/transcript-correction',dependencies=[Depends(owned_case),Depends(operator)])
def transcript_correction(case_id:str,body:TranscriptCorrection,request:Request):return HRService(ctx(request)).correct_transcript(case_id,body)
