import React from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {PhoneInterview} from './PhoneInterview';
function response(data:unknown,status=200){return Promise.resolve({ok:status<400,status,json:async()=>data} as Response);}
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function api(available=true){return vi.fn((url:string,options?:RequestInit)=>{
 if(url.endsWith('/capabilities'))return response({phone:{available,missing:available?[]:['ELEVENLABS_PHONE_NUMBER_ID']}});
 if(url.endsWith('/contact'))return response({suggested_numbers:['+12025550123']});
 if(options?.method==='POST')return response({state:'connecting',session_id:'s1',phone_last_four:'0123',provider_final:false,case_status:{status:'interview_call_connecting'},message:'Waiting for provider-confirmed transcript.'});
 return response({error:{code:'NOT_FOUND',message:'No call'}},404);
});}
it('requires explicit permission and operator token before dialling',async()=>{
 const fetcher=api();vi.stubGlobal('fetch',fetcher);render(<PhoneInterview caseId="c1" onResults={vi.fn()}/>);
 await waitFor(()=>expect((screen.getByLabelText('Candidate phone number') as HTMLInputElement).value).toBe('+12025550123'));
 expect((screen.getByText('Call candidate now') as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Recruiter authorization'),{target:{value:'test-recruiter'}});
 fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.click(screen.getByText('Call candidate now'));
 await screen.findByText('Call: connecting');
 const calls=fetcher.mock.calls.filter(([,opts])=>opts?.method==='POST');
 expect(calls).toHaveLength(1);
 expect(JSON.parse(calls[0][1]!.body as string)).toMatchObject({phone_number:'+12025550123',contact_permission:true});
 expect((calls[0][1]!.headers as Record<string,string>)['X-Recruiter-Token']).toBe('test-recruiter');
 expect(document.body.textContent).not.toContain('test-recruiter');
 expect(screen.queryByText('Call candidate now')).toBeNull();
});
it('shows a specific configuration blocker and never silently dials or uses text',async()=>{
 const fetcher=api(false);vi.stubGlobal('fetch',fetcher);render(<PhoneInterview caseId="c1" onResults={vi.fn()}/>);
 await screen.findByText(/Phone calling needs setup: ELEVENLABS_PHONE_NUMBER_ID/);
 expect((screen.getByText('Call candidate now') as HTMLButtonElement).disabled).toBe(true);
 expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(0);
});
