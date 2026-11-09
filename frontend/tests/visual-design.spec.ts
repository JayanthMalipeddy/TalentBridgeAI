import {test, expect, type Page} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
const sample={case_id:'visual-only',mode:'recruitment',role:'Integration Engineer',cv_text:'Fictional visual-test profile',job_description:'API integration and troubleshooting'};
const evidence={source_type:'transcript',source_id:'test-turn',locator:'test-turn',excerpt:'Fictional visual test: I use an idempotency key and bounded retries to avoid duplicate requests.'};
async function fixtures(page:Page){
 await page.route('**/api/**', async route=>{
  const path=new URL(route.request().url()).pathname;
  let data:unknown={};
  if(path.includes('session')&&!path.includes('interviews'))data={workspace_id:'visual-only',csrf_token:'test-only',expires_at:'2099-01-01T00:00:00Z'};
  else if(path==='/api/capabilities')data={sessions:{elevenlabs:false},phone:{available:false,missing:['Visual test: no calls enabled']},providers:{groq:{configured:false}},integrations:{langfuse:{configured:false}}};
  else if(path==='/api/cases')data=route.request().method()==='GET'?[{...sample,status:'report_ready'}]:sample;
  else if(path.endsWith('/report'))data={case_id:sample.case_id,report_version:'visual-test-version',mode:'recruitment',summary:'Fictional visual test report. Evidence and limitations remain visible.',strengths:['Explains retry handling in the test transcript.'],gaps:['Additional evidence is required.'],suggested_next_steps:['Discuss authentication and failure recovery.'],learning_resources:[],draft_email:'Fictional draft for visual verification only.',approval_status:'draft',evidence:Array.from({length:8},(_,i)=>({...evidence,locator:'test-turn-'+i,excerpt:evidence.excerpt.repeat(4)}))};
  else if(path.endsWith('/plan'))data={case_id:sample.case_id,plan_version:'test',questions:Array.from({length:5},(_,i)=>({question_id:'q'+i,skill:'Reliability',question:'How would you recover safely from an API failure?',evidence:[evidence]})),missing_information:[],warnings:['Fictional visual-test plan']};
  else if(path.endsWith('/interview'))return route.fulfill({status:404,json:{error:{message:'No test interview'}}});
  else if(path.startsWith('/api/interviews/'))data={session_id:'visual',case_id:'visual-only',channel:'text',mode:'mock',state:'active',consent_confirmed:true,turns:Array.from({length:14},(_,i)=>({turn_id:'turn-'+i,speaker:i%2?'candidate':'interviewer',question_id:'q1',text:i%2?evidence.excerpt.repeat(3):'How would you troubleshoot a slow integration and verify recovery?',start_ms:null,end_ms:null})),current_turn_id:'turn-13',deadline:null,max_duration_seconds:240,warnings:['Fictional interface test. No provider was contacted.'],question_count:5,question_number:3,plan_version:'test',voice_pending:false,result:null};
  else data={case:sample,status:'report_ready'};
  await route.fulfill({json:data});
 });
}
async function capture(page:Page,name:string,fixture=false){
 if(fixture)await page.evaluate(()=>{if(document.querySelector('#visual-label'))return;const label=document.createElement('div');label.id='visual-label';label.textContent='VISUAL TEST • FICTIONAL DATA • NO LIVE CALL';label.style.cssText='padding:10px;background:#fff1c9;color:#493b18;text-align:center;font:600 12px Arial';document.body.prepend(label);});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await mkdir('../docs/design/screenshots',{recursive:true});
 await page.screenshot({path:'../docs/design/screenshots/'+name+'.png',fullPage:true});
}
for(const width of [1440,820,390])test('full-page surfaces and interactions '+width,async({page})=>{
 await page.setViewportSize({width,height:1000});
 await page.goto('/');
 await expect(page.locator('footer')).toContainText('TalentBridge');
 for(const selector of ['#how','#features','.reverse','.final-cta','footer']){
  await page.locator(selector).scrollIntoViewIfNeeded();
  const styled=await page.locator(selector).evaluate(el=>{const s=getComputedStyle(el);return s.backgroundImage!=='none'||!['rgba(0, 0, 0, 0)','rgb(255, 255, 255)'].includes(s.backgroundColor);});
  expect(styled).toBe(true);
 }
 await capture(page,'landing-'+width);
 await fixtures(page);
 await page.goto('/app');
 await expect(page.getByRole('button',{name:/Continue/})).toBeEnabled();
 await capture(page,'welcome-'+width,true);
 await page.getByRole('button',{name:/Continue/}).click();
 await expect(page.getByRole('button',{name:/Create interview plan/})).toBeEnabled();
 await page.getByLabel('Job description',{exact:true}).focus();
 expect(await page.getByLabel('Job description',{exact:true}).evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
 await capture(page,'form-'+width,true);
 await page.getByRole('button',{name:'Reports',exact:true}).click();
 await page.getByRole('button',{name:'Open report'}).click();
 await expect(page.locator('.report')).toBeVisible();
 for(const summary of await page.locator('.report summary').all())await summary.click();
 await capture(page,'expanded-report-'+width,true);
 await page.goto('/interview/visual#token=visual-test-only');
 await expect(page.getByRole('button',{name:'Submit answer'})).toBeDisabled();
 await page.getByLabel('Your answer').fill('Fictional answer for visual interaction verification.');
 await expect(page.getByRole('button',{name:'Submit answer'})).toBeEnabled();
 await expect(page.getByRole('button',{name:'Stop early'})).toBeVisible();
 await capture(page,'interview-'+width,true);
 await page.emulateMedia({reducedMotion:'reduce'});
 expect(await page.locator('html').evaluate(el=>getComputedStyle(el).scrollBehavior)).toBe('auto');
});

for(const width of [1440,390])test('phone controls and browser voice consent '+width,async({page})=>{
 await page.setViewportSize({width,height:1000});
 await fixtures(page);
 await page.route('**/api/capabilities',route=>route.fulfill({json:{sessions:{elevenlabs:true},phone:{available:true,missing:[]}}}));
 await page.route('**/contact',route=>route.fulfill({json:{suggested_numbers:[]}}));
 await page.route('**/phone-call',route=>route.fulfill({status:404,json:{error:{code:'NOT_FOUND',message:'No test call'}}}));
 await page.goto('/app/new');
 await page.getByRole('button',{name:/Use fictional sample/}).click();
 await page.getByRole('button',{name:/Create interview plan/}).click();
 await page.getByRole('button',{name:'Continue to interview'}).click();
 await expect(page.getByRole('button',{name:'Call candidate now'})).toBeDisabled();
 await page.getByLabel('Candidate phone number').fill('+12025550123');
 await page.getByLabel('Recruiter authorization').fill('test-only-not-a-secret');
 await page.getByRole('checkbox').check();
 await expect(page.getByRole('button',{name:'Call candidate now'})).toBeEnabled();
 await page.getByLabel('Recruiter authorization').fill('');
 await capture(page,'phone-'+width,true);
 await page.route('**/api/interviews/voice',route=>route.fulfill({json:{session_id:'voice',case_id:'visual-only',channel:'elevenlabs',mode:'mock',state:'awaiting_consent',consent_confirmed:false,turns:[],current_turn_id:null,deadline:null,max_duration_seconds:240,warnings:[],question_count:5,question_number:0,plan_version:'test',voice_pending:false,result:null}}));
 await page.goto('/interview/voice#token=visual-test-only');
 await expect(page.getByRole('heading',{name:'Browser voice interview'})).toBeVisible();
 await expect(page.getByRole('button',{name:/I consent/})).toBeEnabled();
 await capture(page,'voice-consent-'+width,true);
});
