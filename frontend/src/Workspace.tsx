import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Brand, Workflow } from "./Landing";
import { EvidenceList, ReportView } from "./Reports";
import { ApiError, openWorkspace, request } from "./api";
import type { Assessment, Case, Mode, Plan, Report } from "./contracts";
import { InterviewPage } from "./features/interview/InterviewPage";
import {PhoneInterview} from "./features/interview/PhoneInterview";
import {ServiceStatus} from "./ServiceStatus";
const steps = ["Details", "Interview plan", "Interview", "Results"];
export function Workspace() {
  const stagePanel = useRef<HTMLElement|null>(null);
  const [operation, setOperation] = useState("");
  const [usePhone, setUsePhone] = useState(true);
  const [voiceAvailable, setVoiceAvailable] = useState(false);
  const [channel, setChannel] = useState<"text"|"elevenlabs">("text");
  const [lastStage, setLastStage] = useState<"plan"|"assess"|"report"|null>(null);
  const [invitation, setInvitation] = useState<{session_id:string; candidate_url:string}|null>(null);
  const [interviewDone, setInterviewDone] = useState(false);
  const [ready, setReady] = useState(false),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [mode, setMode] = useState<Mode>("recruitment"),
    [chosen, setChosen] = useState(location.pathname !== "/app");
  const [cv, setCv] = useState(""),
    [jd, setJd] = useState(""),
    [file, setFile] = useState<File | null>(null);
  const [active, setActive] = useState<Case | null>(null),
    [plan, setPlan] = useState<Plan | null>(null),
    [assessment, setAssessment] = useState<Assessment | null>(null),
    [report, setReport] = useState<Report | null>(null);
  const [cases, setCases] = useState<
      { case_id: string; mode: Mode; role: string; status: string }[]
    >([]),
    [page, setPage] = useState(location.pathname.split("/")[2] || "new"),
    [stage, setStage] = useState(0);
  useEffect(() => {
    if (stage === 0) return;
    const frame = requestAnimationFrame(() => {
      stagePanel.current?.scrollIntoView({block:"start", behavior:"instant"});
      stagePanel.current?.focus({preventScroll:true});
    });
    return () => cancelAnimationFrame(frame);
  }, [stage]);
  async function connect(fresh = false) {
    setLoading(true);
    setError("");
    try {
      await openWorkspace(fresh);
      setReady(true);
      if (fresh) {
        setActive(null);
        setPlan(null);
        setAssessment(null);
        setReport(null);
        setCases([]);
        setStage(0);
      }
    } catch (e) {
      setReady(false);
      setError(
        "Workspace session service unavailable. " + (e as Error).message,
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void connect();
    request<{sessions:{elevenlabs:boolean}}>("/capabilities").then(c => {
      setVoiceAvailable(c.sessions.elevenlabs);
      if (c.sessions.elevenlabs) setChannel("elevenlabs");
    }).catch(() => setVoiceAvailable(false));
  }, []);
  useEffect(() => {
    if (ready && page !== "new" && page !== "status")
      void run(async () => setCases(await request("/cases")));
  }, [ready, page]);
  useEffect(() => {
    const back = () => {
      setPage(location.pathname.split("/")[2] || "new");
      setChosen(location.pathname !== "/app");
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  async function run(action: () => Promise<void>) {
    setError("");
    setLoading(true);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 401) setReady(false);
    } finally {
      setLoading(false);
      setOperation("");
    }
  }
  function navigate(next: string) {
    setPage(next);
    history.pushState(null, "", "/app/" + next);
    if (next === "new") {
      setActive(null);
      setInvitation(null);
      setUsePhone(true);
      setInterviewDone(false);
      setPlan(null);
      setReport(null);
      setAssessment(null);
      setStage(0);
    }
  }
  function chooseFile(f: File | undefined) {
    if (!f) return;
    if (
      !/\.(pdf|docx)$/i.test(f.name) ||
      f.size > 1000000 ||
      f.size === 0
    ) {
      setError("Choose a non-empty PDF or DOCX up to 1 MB.");
      return;
    }
    setFile(f);
    setCv("");
    setError("");
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if ((!file && !cv.trim()) || !jd.trim()) {
      setError("Add a CV and job description before continuing.");
      return;
    }
    await run(async () => {
      setOperation(file ? "Uploading and reading your CV?" : "Saving candidate details?");
      let current = active;
      if (!current) {
        const body = new FormData();
        body.set("mode", mode);
        body.set("role", "Integration Engineer");
        body.set("job_description", jd);
        if (file) body.set("cv_file", file);
        else body.set("cv_text", cv);
        current = await request<Case>("/cases", "POST", body);
        setActive(current);
      }
      setLastStage("plan");
      setOperation("Retrieving knowledge and generating five interview questions. This may take a minute.");
      setPlan(
        await request<Plan>("/cases/" + current.case_id + "/plan", "POST"),
      );
      setStage(1);
    });
  }
  const failure = (error && (
        <div role="alert" className="error" id="workflow-error">
          <strong>Unable to continue</strong>
          <p>{error}</p>
          {ready && chosen && <button type="button" className="secondary" onClick={() => navigate("interviews")}>View saved interviews</button>}
          {ready && active && lastStage && <button type="button" disabled={loading} onClick={() => void run(async () => {
            const path = "/cases/" + active.case_id + "/" + lastStage + "?retry=true";
            if (lastStage === "plan") { setPlan(await request<Plan>(path, "POST")); setStage(1); }
            if (lastStage === "assess") { setAssessment(await request<Assessment>(path, "POST")); setStage(3); }
            if (lastStage === "report") setReport(await request<Report>(path, "POST"));
          })}>Retry {lastStage} after resolving the error (may use provider quota)</button>}
          {!ready && (
            <button type="button" onClick={() => void connect(true)} disabled={loading}>
              Create a new workspace
            </button>
          )}
        </div>
      ));
  const notice = (
    <>
      {loading && !(chosen && page === "new" && stage === 0) && (
        <p role="status" className="notice">
          Waiting for the workspace service…
        </p>
      )}
      {!(chosen && page === "new" && stage === 0) && failure}
    </>
  );
  if (!chosen)
    return (
      <main className="welcome">
        <div className="welcome-left">
          <Brand />
          <div className="welcome-form">
            <p className="eyebrow">YOUR INTERVIEW WORKSPACE</p>
            <h1>
              What would you
              <br />
              like to do?
            </h1>
            <p>One thoughtful conversation. A clearer way forward.</p>
            <fieldset>
              <legend className="sr-only">Choose your mode</legend>
              {(["recruitment", "mock"] as Mode[]).map((m) => (
                <label
                  className={"mode " + (mode === m ? "selected" : "")}
                  key={m}
                >
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === m}
                    onChange={() => setMode(m)}
                  />
                  <span>
                    <strong>
                      {m === "mock"
                        ? "Practise an interview"
                        : "Screen a candidate"}
                    </strong>
                    <small>
                      {m === "mock"
                        ? "Try a mock interview and receive private feedback."
                        : "Create a structured interview and review evidence before preparing a client report."}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
            {notice}
            <button
              disabled={!ready || loading}
              onClick={() => setChosen(true)}
            >
              Continue →
            </button>
            <small>No signup required. Prototype usage limits apply.</small>
          </div>
          <a href="/">← Back to TalentBridge AI</a>
        </div>
        <div className="welcome-right">
          <p className="eyebrow">FROM POTENTIAL TO PERSPECTIVE</p>
          <h2>
            Give every interview
            <br />a little more clarity.
          </h2>
          <Workflow />
          <p>Four stages. One connected story.</p>
        </div>
      </main>
    );
  return (
    <div className="app-shell">
      <aside>
        <Brand />
        <p className="eyebrow">WORKSPACE</p>
        {[
          ["overview", "Overview"],
          ["new", "New interview"],
          ["interviews", "My interviews"],
          ["reports", "Reports"],
          ["status", "Services and usage"],
        ].map(([key, label]) => (
          <button
            className={page === key ? "active" : ""}
            key={key}
            onClick={() => navigate(key)}
          >
            {label}
          </button>
        ))}
        <div className="sidebar-bottom">
          <small>Private guest workspace</small>
          <label>
            Default mode
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              <option value="recruitment">Recruitment</option>
              <option value="mock">Mock practice</option>
            </select>
          </label>
          <a href="/">← Back to website</a>
        </div>
      </aside>
      <main className="app-main">
        <header className="app-header">
          <div>
            <p className="eyebrow">TALENTBRIDGE AI / {active?.mode || mode}</p>
            <h1>
              {page === "new"
                ? "A better conversation starts here."
                : page === "status"
                  ? "Services and usage"
                : page === "reports"
                  ? "Your reports"
                  : page === "overview"
                    ? "Your workspace"
                    : "My interviews"}
            </h1>
          </div>
          <span className="tag">
            {ready ? "Guest workspace" : "Service unavailable"}
          </span>
        </header>
        {notice}
        {page === "status" ? <ServiceStatus/> : page !== "new" ? (
          <section className="panel">
            <h2>
              {page === "reports"
                ? "Reports for your interviews"
                : "Your interviews"}
            </h2>
            {cases.length === 0 ? (
              <p>No interviews to show. Create an interview to get started.</p>
            ) : (
              cases.map((c) => (
                <div className="case-row" key={c.case_id}>
                  <div>
                    <strong>{c.role}</strong>
                    <p>
                      {c.mode} · {c.status}
                    </p>
                  </div>
                  <button
                    className="secondary"
                    disabled={!ready || loading}
                    onClick={() =>
                      void run(async () => {
                        const data = await request<{
                          case: Case;
                          status: string;
                        }>("/cases/" + c.case_id);
                        if (page === "reports") {
                          const r = await request<Report>(
                            "/cases/" + c.case_id + "/report",
                          );
                          setReport(r);
                          setStage(3);
                        } else {
                          setCv(data.case.cv_text);
                          setJd(data.case.job_description);
                          setMode(data.case.mode);
                          setFile(null);
                          try {
                            setPlan(await request<Plan>("/cases/" + c.case_id + "/plan"));
                            setStage(1);
                            try {
                              await request("/cases/" + c.case_id + "/interview");
                              setStage(2);
                            } catch { /* No saved interview yet. */ }
                          } catch { setPlan(null); setStage(0); }
                          setInvitation(null);
                          setReport(null);
                        }
                        setAssessment(null);
                        setActive(data.case);
                        setPage("new");
                        history.pushState(null, "", "/app/new");
                      })
                    }
                  >
                    Open {page === "reports" ? "report" : "case"}
                  </button>
                </div>
              ))
            )}
            <button onClick={() => navigate("new")}>New interview →</button>
          </section>
        ) : (
          <>
            <ol className="progress">
              {steps.map((s, i) => (
                <li className={stage === i ? "current" : ""} key={s}>
                  <span>{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
            {stage === 0 && (
              <form className="panel" onSubmit={submit}>
                <p className="eyebrow">01 / THE CONTEXT</p>
                <h2>Tell us about the interview.</h2>
                <p>
                  Your CV and role requirements give the conversation its
                  direction.
                </p>
                <div className="form-grid">
                  <label>
                    Mode
                    <select
                      value={active?.mode || mode}
                      disabled={!!active}
                      onChange={(e) => setMode(e.target.value as Mode)}
                    >
                      <option value="recruitment">Recruitment</option>
                      <option value="mock">Mock practice</option>
                    </select>
                  </label>
                  <label>
                    Role
                    <input value="Integration Engineer" readOnly />
                  </label>
                </div>
                <label
                  className="drop"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (!active) chooseFile(e.dataTransfer.files[0]);
                  }}
                >
                  Upload CV<strong>Drop a PDF or DOCX here</strong>
                  <span>or choose a file · up to 1 MB</span>
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    disabled={!!active}
                    onChange={(e) => chooseFile(e.target.files?.[0])}
                  />
                </label>
                {file && (
                  <p>
                    {file.name} · {Math.ceil(file.size / 1024)} KB{" "}
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setFile(null)}
                    >
                      Remove
                    </button>
                  </p>
                )}
                <p className="muted">
                  PDF and DOCX are parsed locally. You can also paste CV text below.
                </p>
                <label>
                  Or paste CV text
                  <textarea
                    rows={5}
                    value={cv}
                    disabled={!!file || !!active}
                    onChange={(e) => setCv(e.target.value)}
                    aria-describedby="form-help workflow-error"
                    aria-invalid={!!error}
                  />
                </label>
                <label>
                  Job description
                  <textarea
                    aria-describedby="form-help workflow-error"
                    aria-invalid={!!error}
                    rows={5}
                    value={jd}
                    disabled={!!active}
                    onChange={(e) => setJd(e.target.value)}
                  />
                </label>
                <p id="form-help">
                  Both a CV and a job description are required. Details stay on
                  this page after a failed request.
                </p>
                {failure}
                {loading && <p role="status" aria-live="polite" className="notice">{operation || "Connecting to your workspace?"}</p>}
                <div className="actions">
                  <button type="submit" disabled={!ready || loading} aria-busy={loading}>
                    {loading ? (ready ? "Creating interview plan?" : "Connecting workspace?") : "Create interview plan ?"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={!!active}
                    onClick={() => {
                      setFile(null);
                      setCv(
                        "Fictional sample: Alex Morgan, Integration Engineer. Three years building REST APIs, webhook integrations and retry queues. Experience with Python, SQL and monitoring.",
                      );
                      setJd(
                        "Fictional sample role: Integration Engineer. Design reliable API integrations, troubleshoot failures, implement authentication and explain technical tradeoffs.",
                      );
                    }}
                  >
                    Use fictional sample CV and job description
                  </button>
                </div>
              </form>
            )}
            {stage === 1 && plan && (
              <section className="panel" ref={stagePanel} tabIndex={-1} aria-label="Generated interview plan">
                <p role="status" className="notice">Interview plan ready. Review the questions, then continue to the interview.</p>
                <p className="eyebrow">02 / INTERVIEW PLAN</p>
                <h2>{active?.role}</h2>
                <p>
                  Duration is not provided by the current planning contract.
                </p>
                {plan.questions.map((q, i) => (
                  <article className="question" key={q.question_id}>
                    <span className="tag">{q.skill}</span>
                    <h3>
                      {i + 1}. {q.question}
                    </h3>
                    <EvidenceList items={q.evidence} />
                  </article>
                ))}
                {[...plan.missing_information, ...plan.warnings].map((w, i) => (
                  <p className="notice" key={i}>
                    {w}
                  </p>
                ))}
                <button onClick={() => setStage(2)}>
                  Continue to interview →
                </button>
              </section>
            )}
            {stage === 2 && (
              <section className="panel" ref={stagePanel} tabIndex={-1}>
                <p className="eyebrow">03 / INTERVIEW</p>
                <h2>Your interview</h2>
                {active?.mode === "recruitment" && usePhone ? <>
                  <PhoneInterview key={active.case_id} caseId={active.case_id} onResults={(a,r)=>{setAssessment(a);setReport(r);setStage(3);}} />
                  <button className="secondary" onClick={()=>setUsePhone(false)}>Use text or browser interview instead</button>
                </> : <>
                {!invitation && <>
                  <label>Interview channel<select value={channel} onChange={e => setChannel(e.target.value as "text"|"elevenlabs")}>
                    <option value="elevenlabs" disabled={!voiceAvailable}>ElevenLabs browser voice{!voiceAvailable ? " ? setup required" : ""}</option>
                    <option value="text">Text interview</option>
                  </select></label>
                  <p>{voiceAvailable ? "The candidate opens the invitation and speaks with the AI interviewer using their microphone." : "ElevenLabs voice setup is incomplete. Text is available as a clearly labelled alternative."}</p>
                </>}
                {!invitation && <button disabled={loading || !active} onClick={() => void run(async () => {
                  const link = await request<{session_id:string; candidate_url:string}>("/cases/" + active!.case_id + "/sessions", "POST", {channel});
                  setInvitation(link);
                })}>Start {channel === "elevenlabs" ? "voice" : "text"} interview</button>}
                {invitation && <>
                  <p><a href={invitation.candidate_url} target="_blank" rel="noreferrer">Open candidate invitation</a></p>
                  <InterviewPage sessionId={invitation.session_id} candidateToken={new URLSearchParams(new URL(invitation.candidate_url).hash.slice(1)).get("token") || ""} onCompleted={() => setInterviewDone(true)} />
                </>}
                <h3>Processing status</h3>
                <p>
                  Transcript: awaiting interview · Assessment: not started ·
                  Report: not started
                </p>
                <button
                  disabled={!ready || loading}
                  onClick={() =>
                    void run(async () => {
                      if (!active) return;
                      setLastStage("assess");
                      setAssessment(
                        await request<Assessment>(
                          "/cases/" + active.case_id + "/assess",
                          "POST",
                        ),
                      );
                      setStage(3);
                    })
                  }
                >
                  Assess saved interview
                </button>
                </>}
              </section>
            )}
            {stage === 3 && (
              <section className="panel" ref={stagePanel} tabIndex={-1}>
                {assessment && (
                  <>
                    <h2>Assessment</h2>
                    {assessment.recommendation && <p><strong>Recommendation: {assessment.recommendation.replaceAll("_", " ")}</strong></p>}
                    <p>Scored skill coverage: {Math.round(assessment.coverage * 100)}%. This is not the candidate's overall score.</p>
                    <p>Review the answer evidence and limitations below. The recommendation supports the recruiter's final decision.</p>
                    {assessment.skills.map((s) => (
                      <article className="question" key={s.skill}>
                        <h3>{s.skill}</h3>
                        <span className="tag">
                          {s.status.replaceAll("_", " ")}
                        </span>
                        {s.score !== null && <p>Score: {s.score}/3</p>}
                        <p>{s.rationale}</p>
                        {s.needs_verification && (
                          <p>Verification recommended</p>
                        )}
                        <EvidenceList items={s.evidence} />
                      </article>
                    ))}
                    {assessment.limitations.map((x, i) => (
                      <p key={i}>{x}</p>
                    ))}
                    <button
                      disabled={!ready || loading}
                      onClick={() =>
                        void run(async () => {
                          setLastStage("report");
                          setReport(
                            await request<Report>(
                              "/cases/" + active!.case_id + "/report",
                              "POST",
                            ),
                          );
                        })
                      }
                    >
                      Prepare report
                    </button>
                  </>
                )}
                {report && (
                  <ReportView
                    report={report}
                    busy={loading}
                    approve={() =>
                      void run(async () =>
                        setReport(
                          await request<Report>(
                            "/cases/" + report.case_id + "/approve",
                            "POST",
                            { report_version: report.report_version },
                          ),
                        ),
                      )
                    }
                  />
                )}
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
