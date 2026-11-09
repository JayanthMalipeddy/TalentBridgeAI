import {test,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
for(const width of [1440,390])test('HR review exact recipients and explicit decision '+width,async({page})=>{
 const config={job_title:'Integration Engineer',job_reference:'VISUAL-001',client_name:'Fictional client',client_contact_name:'Hiring team',client_email:'client@example.com',candidate_name:'Fictional candidate',candidate_email:'candidate@example.com',candidate_email_confirmed:true,cv_sharing_authorized:true,recruiter_name:'Demo reviewer',agency_name:'TalentBridge',recruiter_contact:'hr@example.com',threshold:70,approved_summary:'Fictional visual-test summary: candidate explained safe retries.',templates:{}};
 const criterion={criterion_id:'c1',question_id:'q1',title:'Integration reliability',weight:1,essential:true,expected_principles:'Bounded retry and idempotency',anchors:{'0':'Incorrect','1':'Limited','2':'Partial','3':'Correct','4':'Complete'}};
 let decision:unknown=null;let calls=0;
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;let data:unknown={};
  if(path.endsWith('/session')||path.endsWith('/guest-session'))data={workspace_id:'test',csrf_token:'test',expires_at:'2099-01-01T00:00:00Z'};
  else if(path==='/api/capabilities')data={sessions:{elevenlabs:false}};
  else if(path==='/api/cases')data=[{case_id:'visual',role:'Integration Engineer',mode:'recruitment',status:'completed'}];
  else if(path.endsWith('/plan'))data={questions:[{question_id:'q1',skill:'Reliability',question:'How do you retry safely?'}]};
  else if(path.endsWith('/gmail/status'))data={configured:true,connected:true,sender:'sender@example.com',send_enabled:false,reconnect_required:false};
  else if(path.endsWith('/review'))data={preview_version:'exact-preview',case:{role:'Integration Engineer',cv_text:'Fictional CV for visual verification.',job_description:'Design reliable job-related API integrations.'},config:{data:config,version:'config-1'},rubric:{criteria:[criterion],reviewer:'HR',version:'rubric-1'},assessment:{version:'assessment-1',score:75,threshold:70,recommendation:'recommend_shortlist',explanation:'Fictional screenshot fixture, not a live assessment.',criteria:[{criterion,score:3,rationale:'Explains idempotency and bounded retries.',evidence:[{turn_id:'turn-2',excerpt:'Fictional answer: use an idempotency key and bounded retries.'}],uncertainty:''}]},assessment_current:true,cv:{filename:'fictional-cv.txt',size:128,sha256:'test-content-hash'},sender:'sender@example.com',messages:{client:{subject:'Candidate Submission — Fictional candidate',body:'Fictional preview for visual verification only.'},candidate:{subject:'Application update',body:'Fictional confirmation after client submission.'},rejection:{subject:'Application update',body:'Fictional rejection template.'}},interview_status:'completed',transcript_status:'final',processing:{status:'assessment_ready'},decision,outbox:[]};
  else if(path.endsWith('/decision')){expect(route.request().headers()['x-recruiter-token']).toBe('test-only');const body=route.request().postDataJSON();expect(body.preview_version).toBe('exact-preview');expect(body.outcome).toBe('shortlist');calls++;decision={outcome:'shortlist',reviewer:body.reviewer,reason:body.reason,reviewed_at:new Date().toISOString()};data=decision;}
  else throw Error('Unexpected API request '+path);
  await route.fulfill({json:data});
 });
 await page.setViewportSize({width,height:1000});await page.goto('/app/interviews');
 await page.getByRole('button',{name:'HR review and emails'}).click();
 await page.getByLabel('Recruiter authorization').fill('test-only');await page.getByRole('button',{name:'Open HR review'}).click();
 await expect(page.getByRole('button',{name:'Approve shortlist and submit'})).toBeDisabled();
 await expect(page.getByLabel('Candidate name',{exact:true})).toHaveValue('Fictional candidate');
 await expect(page.getByLabel('Agency name',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Confirm rubric reviewed'})).toHaveCount(0);
 await page.getByLabel('Reviewer name',{exact:true}).fill('Test HR');await page.getByLabel('Decision / correction reason').fill('Reviewed job-related evidence against the role criteria.');
 await expect(page.getByRole('button',{name:'Approve shortlist and submit'})).toBeEnabled();
 await page.getByText('Client submission + CV',{exact:true}).click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.evaluate(()=>{const d=document.createElement('div');d.textContent='VISUAL TEST • FICTIONAL ASSESSMENT • MOCKED EMAIL DELIVERY';d.style.cssText='padding:12px;background:#fff1c9;color:#463718;text-align:center';document.body.prepend(d);});
 await mkdir('../docs/design/screenshots',{recursive:true});await page.screenshot({path:'../docs/design/screenshots/hr-review-'+width+'.png',fullPage:true});
 await page.getByRole('button',{name:'Approve shortlist and submit'}).click();expect(calls).toBe(1);
 await expect(page.getByText('Recorded: shortlist',{exact:false})).toBeVisible();
});
