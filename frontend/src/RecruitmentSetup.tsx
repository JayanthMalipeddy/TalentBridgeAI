import {useState} from 'react';
import {request} from './api';
import type {Config} from './HRReview';

export function RecruitmentSetup({caseId,onReady}:{caseId:string;onReady:()=>void}) {
  const [token,setToken]=useState(''),[config,setConfig]=useState<Config|null>(null);
  const [attachment,setAttachment]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const base='/hr/cases/'+caseId,headers={'X-Recruiter-Token':token};
  async function prepare(){
    setBusy(true);setError('');
    try {
      const review=await request<{interview_started?:boolean;config:{data:Config}|null;rubric:unknown;cv:{filename:string}|null;case:{role:string}}>(base+'/review','GET',undefined,headers);
      if(review.interview_started){onReady();return;}
      const extracted=review.rubric&&review.config?null:await request<{candidate_name:string;candidate_email:string|null;suggested_numbers?:string[]}>(base+'/prepare','POST',{},headers);
      setAttachment(review.cv?.filename??'Original CV missing: upload it in HR review before continuing.');
      setConfig(review.config?.data??{job_title:review.case.role,job_reference:'',client_name:'',client_contact_name:'',client_email:null,candidate_name:extracted?.candidate_name??'',candidate_email:extracted?.candidate_email??null,candidate_phone:extracted?.suggested_numbers?.length===1?extracted.suggested_numbers[0]:null,candidate_email_confirmed:false,cv_sharing_authorized:false,recruiter_name:'',recruiter_contact:'',agency_name:'',threshold:70,approved_summary:'',templates:{}});
    } catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function change(key:keyof Config,value:unknown){setConfig(c=>c?{...c,[key]:value,...(key==='candidate_email'?{candidate_email_confirmed:false}:{}),...(['client_email','client_name','candidate_name'].includes(key)?{cv_sharing_authorized:false}:{})}:null);}
  return <section className="hr-section" aria-label="Recruitment setup before interview">
    <h3>Recruitment details before the interview</h3>
    <p>Candidate details come from the CV. The LLM prepares the scoring rubric from the job and interview plan. These details and the same CV carry into final HR review.</p>
    {!config&&<><label>Recruiter authorization<input type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></label><button disabled={busy||!token} onClick={()=>void prepare()}>{busy?'Preparing candidate details and AI rubric…':'Load CV details and prepare rubric'}</button></>}
    {error&&<p className="error" role="alert">{error}</p>}
    {config&&<form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await request(base+'/configuration','POST',config,headers);await request(base+'/ready','POST',{},headers);onReady();}catch(err){setError((err as Error).message);}finally{setBusy(false);}}}>
      <div className="form-grid">{([['job_title','Job title'],['job_reference','Job reference'],['client_name','Company / client'],['client_contact_name','Client contact name'],['client_email','Client email'],['candidate_name','Candidate name (from CV)'],['candidate_email','Candidate email (from CV)'],['candidate_phone','Candidate mobile (include country code)'],['recruiter_name','Recruiter name for emails'],['recruiter_contact','Recruiter contact']] as const).map(([key,label])=><label key={key}>{label}<input required={key!=='client_contact_name'&&key!=='candidate_phone'} type={key.endsWith('email')?'email':'text'} value={String(config[key]??'')} onChange={e=>change(key,key==='candidate_phone'?(e.target.value.replace(/[ ()-]/g,'')||null):e.target.value)}/></label>)}</div>
      <p>Original CV attachment: <strong>{attachment}</strong></p>
      <p>Check the extracted name and email. If missing from the CV, enter confirmed details; the system does not invent them.</p>
      <label>Assessment threshold (%)<input type="number" min={60} max={70} step={0.1} required value={config.threshold} onChange={e=>change('threshold',Number(e.target.value))}/></label>
      <div className="hr-checks"><label><input type="checkbox" required checked={config.candidate_email_confirmed} onChange={e=>change('candidate_email_confirmed',e.target.checked)}/>I confirmed the candidate email address.</label><label><input type="checkbox" required checked={config.cv_sharing_authorized} onChange={e=>change('cv_sharing_authorized',e.target.checked)}/>The candidate authorized sharing this CV with this client.</label></div>
      <button disabled={busy}>Candidate ready for interview</button>
    </form>}
  </section>;
}
