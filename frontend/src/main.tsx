import { createRoot } from "react-dom/client";
import { Landing, Brand } from "./Landing";
import { Workspace } from "./Workspace";
import "./style.css";
function App() {
  if (location.pathname.startsWith("/interview/")) {
    if (location.hash) history.replaceState(null, "", location.pathname);
    return (
      <main className="panel candidate">
        <Brand />
        <h1>Interview integration pending</h1>
        <p>
          This invitation cannot start an interview in the current build.
          Contact your recruiter for next steps. Recruiter plans and reports are
          private.
        </p>
      </main>
    );
  }
  return location.pathname.startsWith("/app") ? <Workspace /> : <Landing />;
import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {InterviewPage} from './features/interview/InterviewPage';

function App() {
  const [health, setHealth] = useState('Checking backend…');
  const [token, setToken] = useState('');
  const [message, setMessage] = useState('');
  const [capabilities, setCapabilities] = useState<Record<string, {available:boolean}>>({});
  const candidate = location.pathname.startsWith('/interview/');
  const [candidateToken] = useState(() => new URLSearchParams(location.hash.slice(1)).get('token') ?? '');
  useEffect(() => {
    // Keep candidate tokens out of server URLs, referrers and browser history.
    if (location.hash) history.replaceState(null, '', location.pathname);
    fetch('/api/health').then(r => {if (!r.ok) throw Error(); return r.json()}).then(() => setHealth('Backend connected')).catch(() => setHealth('Backend unavailable — start the API on port 8000'));
    fetch('/api/capabilities').then(r => r.json()).then(d => setCapabilities(d.agents ?? {})).catch(() => {});
  }, []);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage('Creating case…');
    try {
      const response = await fetch('/api/cases', {method:'POST', headers:{Authorization: 'Bearer ' + token}, body: new FormData(event.currentTarget)});
      const data = await response.json();
      setMessage(response.ok ? 'Case created: ' + data.case_id : data.error?.message ?? 'Request failed');
    } catch { setMessage('Could not reach backend'); }
  }
  return <main className="max-w-4xl mx-auto px-6 py-12">
    <p className="text-sm font-semibold text-teal-700">TALENTBRIDGE AI · FOUNDATION</p>
    <h1 className="text-4xl font-bold mt-3">Evidence-led interview workspace</h1>
    <p className="mt-4" role="status">{health}</p>
    <div className="grid sm:grid-cols-4 gap-3 my-8">{Object.entries(capabilities).map(([name, c]) => <div className="rounded-xl border border-slate-200 bg-white p-4" key={name}><h2 className="capitalize font-semibold">{name}</h2><p className="text-sm mt-2">{c.available ? 'Available' : 'Not implemented'}</p></div>)}</div>
    {candidate ? <InterviewPage sessionId={location.pathname.split('/')[2] ?? ''} candidateToken={candidateToken}/> : <form onSubmit={submit} className="bg-white rounded-xl p-6 grid gap-4">
      <h2 className="text-xl font-semibold">Create a case</h2>
      <p className="text-sm">Agent results become available after the team integrates the agents.</p>
      <label>Recruiter token<input className="block border rounded p-2 w-full" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required /></label>
      <p className="text-xs text-slate-600">Token stays in memory for this page only.</p>
      <label>Mode<select name="mode" className="block border rounded p-2"><option value="recruitment">Recruitment</option><option value="mock">Mock practice</option></select></label>
      <label>Role<input name="role" className="block border rounded p-2 w-full" required /></label>
      <label>CV text<textarea name="cv_text" className="block border rounded p-2 w-full" rows={4} required /></label>
      <label>Job description<textarea name="job_description" className="block border rounded p-2 w-full" rows={4} required /></label>
      <button className="bg-teal-800 text-white rounded px-4 py-3" type="submit">Create case</button>
      <p aria-live="polite">{message}</p>
    </form>}
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
