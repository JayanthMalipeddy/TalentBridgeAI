import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {RecruitmentSetup} from './RecruitmentSetup';
import {request} from './api';
vi.mock('./api',()=>({request:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('prefills CV identity and retains original attachment before interview',async()=>{
 const api=vi.mocked(request);const ready=vi.fn();
 api.mockResolvedValueOnce({config:null,rubric:null,cv:{filename:'original.pdf'},case:{role:'Engineer'}})
    .mockResolvedValueOnce({candidate_name:'Alex Morgan',candidate_email:'alex@example.com'})
    .mockResolvedValueOnce({});
 render(<RecruitmentSetup caseId="case-1" onReady={ready}/>);
 fireEvent.change(screen.getByLabelText('Recruiter authorization'),{target:{value:'test-token'}});
 fireEvent.click(screen.getByText('Load CV details and prepare rubric'));
 await waitFor(()=>expect((screen.getByLabelText('Candidate name (from CV)') as HTMLInputElement).value).toBe('Alex Morgan'));
 expect((screen.getByLabelText('Candidate email (from CV)') as HTMLInputElement).value).toBe('alex@example.com');
 expect(screen.getByText('original.pdf')).toBeTruthy();expect(screen.queryByLabelText('Agency name')).toBeNull();
 for(const label of ['Job reference','Company / client','Recruiter name for emails','Recruiter contact'])fireEvent.change(screen.getByLabelText(label),{target:{value:'Confirmed detail'}});
 fireEvent.change(screen.getByLabelText('Client email'),{target:{value:'client@example.com'}});
 for(const box of screen.getAllByRole('checkbox'))fireEvent.click(box);
 fireEvent.submit(screen.getByText('Save details and continue to interview').closest('form')!);
 await waitFor(()=>expect(ready).toHaveBeenCalledOnce());
 expect(api.mock.calls[2][2]).toMatchObject({candidate_name:'Alex Morgan',candidate_email:'alex@example.com',client_email:'client@example.com',candidate_email_confirmed:true,cv_sharing_authorized:true,agency_name:''});
});
it('shows real preparation failure without fabricated identity or rubric',async()=>{
 vi.mocked(request).mockRejectedValueOnce(new Error('Provider budget exhausted'));
 render(<RecruitmentSetup caseId="case-1" onReady={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('Recruiter authorization'),{target:{value:'test-token'}});
 fireEvent.click(screen.getByText('Load CV details and prepare rubric'));
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('Provider budget exhausted'));
 expect(screen.queryByLabelText('Candidate name (from CV)')).toBeNull();
});

it('resumes existing interviews without preparing or replacing a rubric',async()=>{
 const ready=vi.fn();vi.mocked(request).mockResolvedValueOnce({interview_started:true,config:null,rubric:null,cv:null,case:{role:'Engineer'}});
 render(<RecruitmentSetup caseId="existing" onReady={ready}/>);
 fireEvent.change(screen.getByLabelText('Recruiter authorization'),{target:{value:'test-token'}});
 fireEvent.click(screen.getByText('Load CV details and prepare rubric'));
 await waitFor(()=>expect(ready).toHaveBeenCalledOnce());
 expect(request).toHaveBeenCalledTimes(1);
 expect(vi.mocked(request).mock.calls[0][0]).toBe('/hr/cases/existing/review');
});
