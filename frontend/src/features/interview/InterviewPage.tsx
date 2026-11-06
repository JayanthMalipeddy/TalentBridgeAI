import {useCallback, useEffect, useRef, useState} from 'react';
import {ConversationProvider, useConversation} from '@elevenlabs/react';

type Turn = {turn_id:string; speaker:'interviewer'|'candidate'; question_id:string|null; text:string; start_ms:number|null; end_ms:number|null};
type Session = {
  session_id:string; case_id:string; channel:'text'|'elevenlabs'; mode:'recruitment'|'mock';
  state:string; consent_confirmed:boolean; turns:Turn[]; current_turn_id:string|null;
  deadline:string|null; max_duration_seconds:number; warnings:string[]; question_count:number;
  question_number:number; plan_version:string; voice_pending:boolean;
  result: {status:string; turns:Turn[]; duration_seconds:number} | null;
};
export type InterviewPageProps = {sessionId:string; candidateToken:string};

export function InterviewPage(props:InterviewPageProps) {
  return <ConversationProvider><Interview {...props}/></ConversationProvider>;
}

function Interview({sessionId, candidateToken}:InterviewPageProps) {
  const [session, setSession] = useState<Session|null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState('');
  const [clock, setClock] = useState(Date.now());
  const [voiceStarted, setVoiceStarted] = useState(false);
  const ended = useRef(false);
  const pendingAnswer = useRef<{turn:string; text:string; id:string}|null>(null);
  const conversation = useConversation({onError: () => setError('Voice connection failed. Your transcript remains pending until confirmed by ElevenLabs.')});
  const api = useCallback(async (suffix:string, body?:unknown) => {
    if (!candidateToken) throw Error('This link has no candidate token. Reopen the original invitation link.');
    const response = await fetch(`/api/interviews/${encodeURIComponent(sessionId)}${suffix}`, {
      method:body === undefined ? 'GET' : 'POST',
      headers:{Authorization:`Bearer ${candidateToken}`, ...(body === undefined ? {} : {'Content-Type':'application/json'})},
      body:body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw Error(response.status === 401 ? 'This candidate link is invalid or expired. Contact your recruiter.' : data.error?.message ?? 'Interview request failed.');
    return data;
  }, [sessionId, candidateToken]);
  const refresh = useCallback(async () => {setSession(await api(''));}, [api]);
  useEffect(() => {refresh().catch(e => setError(e.message));}, [refresh]);
  useEffect(() => {const id = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(id);}, []);
  useEffect(() => {
    if (!session || (!session.voice_pending && session.state !== 'processing')) return;
    const id = setInterval(() => {refresh().catch(e => setError(e.message));}, 3000);
    return () => clearInterval(id);
  }, [session?.voice_pending, session?.state, refresh]);
  const terminal = session && ['completed','incomplete','declined'].includes(session.state);
  const remaining = session?.deadline ? Math.max(0, Math.ceil((Date.parse(session.deadline)-clock)/1000)) : null;
  useEffect(() => {
    if (remaining !== 0 || ended.current || !session || terminal) return;
    ended.current = true;
    Promise.resolve(conversation.endSession()).finally(() => {
      api('/stop', {withdraw_consent:false}).then(setSession).catch(e => setError(e.message));
    });
  }, [remaining, terminal, api, session, conversation]);

  async function action(path:string, body:unknown={}) {
    setBusy(true); setError('');
    try {setSession(await api(path, body));} catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function submit() {
    if (!session?.current_turn_id || !answer.trim()) return;
    const turn = session.current_turn_id;
    if (pendingAnswer.current?.turn !== turn || pendingAnswer.current?.text !== answer.trim()) {
      pendingAnswer.current = {turn, text:answer.trim(), id:crypto.randomUUID()};
    }
    setBusy(true); setError('');
    try {
      setSession(await api('/text-answer', {turn_id:turn, request_id:pendingAnswer.current.id, text:answer.trim()}));
      setAnswer(''); pendingAnswer.current = null;
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function startVoice() {
    setBusy(true); setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw Error('Microphone access requires HTTPS or localhost and a supported browser.');
      const stream = await navigator.mediaDevices.getUserMedia({audio:true});
      stream.getTracks().forEach(track => track.stop());
      const authorization = await api('/voice-token', {});
      setVoiceStarted(true);
      await conversation.startSession({signedUrl:authorization.signed_url, connectionType:'websocket', dynamicVariables:authorization.dynamic_variables});
      await refresh();
    } catch {setError('Could not start voice. Check microphone permission and provider configuration. If authorization was issued, ask the recruiter to reconcile it before retrying.');}
    finally {setBusy(false);}
  }
  async function stop(withdraw:boolean) {
    try {await conversation.endSession();} finally {await action('/stop', {withdraw_consent:withdraw});}
  }
  return <section className="bg-white rounded-xl p-6 grid gap-4" aria-label="Candidate interview">
    <h2 className="text-2xl font-semibold">{session?.channel === 'elevenlabs' ? 'Browser voice interview' : 'Text interview'}</h2>
    <p>English · Integration Engineer · AI interview assistant</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {!session && !error && <p role="status">Loading your interview…</p>}
    {session && <>
      <p role="status">Status: {session.state.replaceAll('_',' ')} {remaining !== null && `· ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} remaining`}</p>
      {session.state === 'awaiting_consent' && <>
        <p>Your answers will be transcribed and saved for {session.mode === 'mock' ? 'your private mock feedback' : 'recruiter review'}. {session.channel === 'elevenlabs' && 'Voice audio is processed by ElevenLabs.'} You can stop or withdraw consent. Declining saves no answers. No phone call is placed.</p>
        <button disabled={busy} className="bg-teal-800 text-white rounded p-3" onClick={() => action('/consent', {confirmed:true})}>I consent — begin interview</button>
        <button disabled={busy} className="border rounded p-3" onClick={() => action('/consent', {confirmed:false})}>I do not consent</button>
      </>}
      {session.channel === 'elevenlabs' && !terminal && <>
        <p>Connection: {conversation.status}. Allow microphone access when prompted. Live speech is confirmed through the provider transcript after the session.</p>
        {session.consent_confirmed && <button disabled={busy || voiceStarted} className="bg-teal-800 text-white rounded p-3" onClick={startVoice}>Start browser voice</button>}
        <button disabled={busy || voiceStarted} className="border rounded p-3" onClick={() => action('/use-text')}>Use text interview instead</button>
      </>}
      {session.turns.map(t => <article key={t.turn_id} className="border-l-4 border-teal-600 pl-4"><p className="text-sm font-semibold capitalize">{t.speaker}</p><p className="whitespace-pre-wrap">{t.text}</p></article>)}
      {session.channel === 'text' && session.state === 'active' && <form onSubmit={e => {e.preventDefault(); void submit();}} className="grid gap-3">
        <label>Your answer<textarea value={answer} onChange={e => setAnswer(e.target.value)} maxLength={12000} required className="block border rounded p-3 w-full" rows={5}/></label>
        <button disabled={busy || !answer.trim()} className="bg-teal-800 text-white rounded p-3">{busy ? 'Saving answer…' : 'Submit answer'}</button>
      </form>}
      {session.state === 'ready_to_complete' && <button disabled={busy} className="bg-teal-800 text-white rounded p-3" onClick={() => action('/complete')}>Complete interview</button>}
      {session.consent_confirmed && !terminal && <div className="flex gap-4">
        <button disabled={busy} className="border rounded p-3" onClick={() => stop(false)}>Stop early</button>
        <button disabled={busy} className="border rounded p-3" onClick={() => stop(true)}>Withdraw consent</button>
      </div>}
      {session.voice_pending && <p>Waiting for the authoritative provider transcript. A browser disconnect is not proof of completion.</p>}
      {terminal && <p>{session.state === 'completed' ? 'Interview saved. Assessment and reporting will be available after those modules are integrated.' : session.state === 'declined' ? 'Consent declined or withdrawn. No interview transcript is retained by this application.' : 'Interview saved as incomplete. Missing answers remain unassessed.'}</p>}
      {session.warnings.map((w,i) => <p className="text-sm text-amber-800" key={i}>{w}</p>)}
    </>}
  </section>;
}
