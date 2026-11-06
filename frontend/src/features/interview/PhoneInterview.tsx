import {useEffect, useRef, useState} from 'react';
import {ApiError, request} from '../../api';
import type {Assessment, Report} from '../../contracts';
type Call = {state:string; session_id:string; phone_last_four:string; provider_final:boolean; interview_status:string|null; case_status:{status:string;failure?:{code:string;message:string}|null}; message:string};
type Props = {caseId:string; onResults:(assessment:Assessment,report:Report)=>void};
export function PhoneInterview({caseId,onResults}:Props) {
  const [number,setNumber]=useState(''),[token,setToken]=useState(''),[permission,setPermission]=useState(false);
  const [call,setCall]=useState<Call|null>(null),[missing,setMissing]=useState<string[]>([]),[ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const requestId=useRef(crypto.randomUUID());
  const [uncertain,setUncertain]=useState(false);
  useEffect(()=>{void (async()=>{
    try {
      const c=await request<{phone:{available:boolean;missing:string[]}}>('/capabilities');
      setReady(c.phone.available);setMissing(c.phone.missing);
      const contacts=await request<{suggested_numbers:string[]}>(`/cases/${caseId}/contact`);
      if(contacts.suggested_numbers.length===1)setNumber(contacts.suggested_numbers[0]);
      try {setCall(await request<Call>(`/cases/${caseId}/phone-call`));}
      catch(e){if(!(e instanceof ApiError && e.status===404))throw e;}
    } catch(e){setError((e as Error).message);}
  })();},[caseId]);
  useEffect(()=>{
    if(!call || ['report_ready','failed'].includes(call.case_status.status) || ['declined','needs_review','dial_unknown'].includes(call.state))return;
    const id=setInterval(()=>{request<Call>(`/cases/${caseId}/phone-call`).then(setCall).catch(e=>setError(e.message));},5000);
    return()=>clearInterval(id);
  },[caseId,call?.state,call?.case_status.status]);
  async function dial(){
    setBusy(true);setError('');setUncertain(true);
    try {
      const result=await request<Call>(`/cases/${caseId}/phone-call`,'POST',{phone_number:number,contact_permission:permission,request_id:requestId.current},{'X-Recruiter-Token':token});
      setCall(result);setToken('');setUncertain(false);
    }catch(e){setError((e as Error).message);if(e instanceof ApiError && e.code!=='NETWORK_ERROR')setUncertain(false);}
    finally{setBusy(false);}
  }
  return <section aria-label="Phone interview" className="phone-interview">
    <h3>Call the candidate with ElevenLabs</h3>
    <p>The AI interviewer calls the confirmed number, asks permission to transcribe, and asks the planned questions aloud. After the call, the confirmed transcript is assessed and a report is prepared automatically.</p>
    {!ready && <p role="status" className="notice">Phone calling needs setup: {missing.join(', ') || 'checking provider configuration'}. A Twilio number must be connected in the ElevenLabs account.</p>}
    {error && <p role="alert">{error}</p>}
    {!call && <>
      <label>Candidate phone number<input type="tel" autoComplete="off" placeholder="+country code and number" value={number} onChange={e=>{setNumber(e.target.value);requestId.current=crypto.randomUUID();}} disabled={busy||uncertain}/></label>
      <p>Confirm the number extracted from the CV, or enter it with its country code. Uploading a CV never places a call automatically.</p>
      <label>Recruiter authorization<input type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)} placeholder="Recruiter token"/></label>
      <label className="phone-permission"><input type="checkbox" checked={permission} onChange={e=>setPermission(e.target.checked)} disabled={busy||uncertain}/>The candidate agreed to receive this interview call.</label>
      <button disabled={!ready||busy||uncertain||!permission||!token||!/^\+[1-9]\d{7,14}$/.test(number)} onClick={()=>void dial()}>{busy?'Requesting call…':'Call candidate now'}</button>
      {uncertain&&!busy && <button className="secondary" onClick={async()=>{try{setCall(await request<Call>(`/cases/${caseId}/phone-call`));}catch(e){setError('Call outcome needs operator review. Do not place another call. '+(e as Error).message);}}}>Check existing call status</button>}
    </>}
    {call && <>
      <p role="status"><strong>Call: {call.state.replaceAll('_',' ')}</strong> · Number ending {call.phone_last_four}</p>
      <p>{call.message}</p><p>Processing: {call.case_status.status.replaceAll('_',' ')}</p>
      {call.case_status.failure && <p role="alert">{call.case_status.failure.message}</p>}
      <p>One call attempt per case. Refreshing this page does not redial. Stop requests are handled by the voice agent; the recruiter supervises through ElevenLabs.</p>
      {call.case_status.status==='report_ready' && <button onClick={async()=>{try{const a=await request<Assessment>(`/cases/${caseId}/assessment`);const r=await request<Report>(`/cases/${caseId}/report`);onResults(a,r);}catch(e){setError((e as Error).message);}}}>View assessment and report</button>}
    </>}
  </section>;
}
