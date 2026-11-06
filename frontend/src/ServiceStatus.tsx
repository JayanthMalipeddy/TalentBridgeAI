import {useEffect, useState} from 'react';
import {request} from './api';
export function ServiceStatus() {
  const [capabilities,setCapabilities]=useState<unknown>(null);
  const [token,setToken]=useState('');
  const [usage,setUsage]=useState<unknown>(null);
  const [error,setError]=useState('');
  useEffect(()=>{request('/capabilities').then(setCapabilities).catch(e=>setError(e.message));},[]);
  return <section className="panel"><h2>Services and usage</h2>
    <p>Provider availability does not guarantee remaining quota. Pending-review knowledge produces provisional feedback without scores.</p>
    <pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(capabilities,null,2)}</pre>
    <h3>Operator usage records</h3><p>Enter the recruiter token at runtime to view project usage. It is kept only in this page's memory.</p>
    <label>Recruiter token<input type="password" value={token} onChange={e=>setToken(e.target.value)} autoComplete="off" /></label>
    <button onClick={async()=>{try {const r=await fetch('/api/usage',{headers:{Authorization:`Bearer ${token}`}});const d=await r.json();if(!r.ok)throw Error(d.error?.message||'Usage unavailable');setUsage(d);setToken('');setError('');}catch(e){setError((e as Error).message);}}}>Load usage</button>
    {error && <p role="alert">{error}</p>}<pre style={{whiteSpace:'pre-wrap'}}>{usage ? JSON.stringify(usage,null,2):''}</pre>
  </section>;
}
