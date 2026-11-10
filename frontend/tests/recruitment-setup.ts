import {expect,type Page} from '@playwright/test';

// Explicit fixture for UI regression tests only. Never calls a model or sends mail.
export async function completeRecruitmentSetup(page:Page){
 const config={job_title:'Integration Engineer',job_reference:'TEST-1',client_name:'Fictional client',client_contact_name:'Test contact',client_email:'client@example.com',candidate_name:'Test candidate',candidate_email:'candidate@example.com',candidate_email_confirmed:true,cv_sharing_authorized:true,recruiter_name:'Test recruiter',recruiter_contact:'recruiter@example.com',agency_name:'',threshold:70,approved_summary:'',templates:{}};
 await page.route('**/api/hr/cases/*/review',route=>route.fulfill({json:{config:{data:config},rubric:{source:'llm'},cv:{filename:'fictional-original.pdf'},case:{role:'Integration Engineer'}}}));
 await page.route('**/api/hr/cases/*/configuration',route=>route.fulfill({json:{data:config}}));
 await page.route('**/api/hr/cases/*/ready',route=>route.fulfill({json:{ready:true}}));
 await page.getByLabel('Recruiter authorization').fill('test-only');
 await page.getByRole('button',{name:'Load CV details and prepare rubric'}).click();
 await expect(page.getByLabel('Candidate name (from CV)')).toHaveValue('Test candidate');
 await page.getByRole('button',{name:'Candidate ready for interview'}).click();
}
