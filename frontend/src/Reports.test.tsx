import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {ReportView} from './Reports';
afterEach(cleanup);
it('routes an HR assessment report to the email decision instead of legacy report approval',()=>{
 const review=vi.fn(),approve=vi.fn();
 render(<ReportView report={{case_id:'test',mode:'recruitment',report_version:'hr-test',approval_status:'draft',summary:'Synthetic report',strengths:[],gaps:[],evidence:[],suggested_next_steps:[],learning_resources:[],draft_email:null}} approve={approve} reviewDecision={review}/>);
 expect(screen.queryByRole('button',{name:'Approve report'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Review assessment and email decision'}));
 expect(review).toHaveBeenCalledOnce();expect(approve).not.toHaveBeenCalled();
});
