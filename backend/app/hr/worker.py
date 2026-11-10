"""Opt-in by saving recruitment configuration and a frozen scoring rubric."""
from datetime import datetime,timezone
from .service import HRService
from .common import digest,maybe,now
from .outbox import process_one
from ..errors import AppError
async def tick(ctx):
    service=HRService(ctx)
    for cid,config in ctx.repository.all_records('hr_config'):
        try:
            with ctx.repository.transaction() as c:
                binding=service._inputs(c,cid)[4]
                prior=maybe(ctx.repository,c,'hr_run',digest(binding))
                if prior:
                    if prior['state']=='succeeded':
                        service._store_report(c,cid,ctx.repository._get(c,'hr_assessment',cid))
                    if prior['state']=='running' and (datetime.now(timezone.utc)-datetime.fromisoformat(prior['started_at'])).total_seconds()>300:
                        ctx.repository._put(c,'hr_run',digest(binding),{'case_id':cid,'state':'failed','error':'INTERRUPTED_ASSESSMENT_RETRY_REQUIRED'})
                    continue
            await service.assess(cid)
            ctx.repository.put('hr_processing',cid,{'case_id':cid,'status':'assessment_ready','updated_at':now()})
        except AppError as e:
            ctx.repository.put('hr_processing',cid,{'case_id':cid,'status':'waiting' if e.code in ('NOT_FOUND','TRANSCRIPT_PENDING','INSUFFICIENT_TRANSCRIPT') else 'failed','code':e.code,'message':e.message,'updated_at':now()})
        except Exception:
            ctx.repository.put('hr_processing',cid,{'case_id':cid,'status':'failed','code':'ASSESSMENT_FAILED','message':'Inspect configuration and explicitly retry the assessment.','updated_at':now()})
    await process_one(ctx)
