export function Brand() {
  return (
    <a className="brand" href="/">
      <span className="symbol" aria-hidden="true">
        tb
      </span>
      TalentBridge <b>AI</b>
    </a>
  );
}
export const start = (
  <a className="button" href="/app">
    Start for free <span aria-hidden="true">↗</span>
  </a>
);
export function Workflow() {
  return (
    <div className="workflow">
      {["CV Review", "Interview", "Assessment", "Report"].map((x, i) => (
        <div key={x}>
          <span>0{i + 1}</span>
          <strong>{x}</strong>
          <small>
            {
              [
                "Start with the story",
                "Make room for conversation",
                "Follow the evidence",
                "Find the next step",
              ][i]
            }
          </small>
        </div>
      ))}
    </div>
  );
}
export function Landing() {
  return (
    <>
      <header className="hero">
        <nav>
          <Brand />
          <div className="navlinks">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
          </div>
          {start}
        </nav>
        <div className="hero-copy">
          <p className="eyebrow">AI interviews for recruitment and practice</p>
          <h1>
            Better interviews.
            <br />
            <span>Clearer hiring decisions.</span>
          </h1>
          <p>
            Turn CVs and job requirements into structured interviews,
            <br className="desktop" /> evidence-backed assessments and useful
            next steps.
          </p>
          {start}
          <small>
            No signup required. Start with a CV and job description.
          </small>
          <small>Prototype usage limits apply.</small>
        </div>
      </header>
      <main className="landing">
        <div className="preview">
          <div className="preview-side">
            <Brand />
            <p>INTERVIEW WORKSPACE</p>
            <b>Overview</b>
            <span>My interviews</span>
            <span>Reports</span>
          </div>
          <div className="preview-content">
            <span className="tag">Sample preview · fictional content</span>
            <h3>A clearer picture of every interview.</h3>
            <p>Integration Engineer · Interview plan</p>
            <div className="preview-grid">
              <div>
                <small>01 / ROLE-GROUNDED QUESTION</small>
                <h4>
                  How would you make an integration resilient to failures?
                </h4>
                <p>
                  Explore retries, observability and recovery through a
                  structured conversation.
                </p>
              </div>
              <div className="mint">
                <small>EVIDENCE, WITH CONTEXT</small>
                <h4>
                  From conversation
                  <br />
                  to useful next steps.
                </h4>
                <p>Review excerpts alongside each assessed skill.</p>
              </div>
            </div>
          </div>
        </div>
        <section id="how">
          <p className="eyebrow">A LITTLE STRUCTURE. A LOT MORE CLARITY.</p>
          <h2>
            Every conversation.
            <br />A purposeful next step.
          </h2>
          <div className="four">
            {[
              "Upload CV and role requirements.",
              "Run a structured interview.",
              "Review skills and supporting evidence.",
              "Prepare a report or personal practice plan.",
            ].map((x, i) => (
              <article key={x}>
                <span className="number">0{i + 1}</span>
                <h3>{x}</h3>
              </article>
            ))}
          </div>
        </section>
        <section id="features" className="feature">
          <div>
            <p className="eyebrow">BUILT AROUND THE ROLE</p>
            <h2>
              Good questions start
              <br />
              with the right context.
            </h2>
            <p>
              Bring a CV and a job description. Review planned questions and
              source references before the interview.
            </p>
            <p className="muted">
              Planning and interview services are being integrated into this
              prototype.
            </p>
            {start}
          </div>
          <div className="feature-art">
            <span className="tag">Workflow preview</span>
            <Workflow />
          </div>
        </section>
        <section className="feature reverse">
          <div>
            <p className="eyebrow">MAKE THE EVIDENCE USEFUL</p>
            <h2>
              Less guesswork.
              <br />
              More context.
            </h2>
            <p>
              Review skill assessments with supporting excerpts, missing
              evidence and verification recommendations. Practise privately or
              prepare a recruitment report for review.
            </p>
            <p className="muted">
              Voice interviews and live assessments are pending integration.
              Availability is shown in the workspace.
            </p>
          </div>
          <div className="quote-card">
            <span className="tag">Sample preview</span>
            <h3>
              Evidence deserves
              <br />a place in the conversation.
            </h3>
            <hr />
            <p>Skill → interview excerpt → next step</p>
            <span className="tag">No invented hiring scores</span>
          </div>
        </section>
        <section className="final-cta">
          <p className="eyebrow">READY WHEN YOU ARE</p>
          <h2>Your next interview starts here.</h2>
          {start}
        </section>
      </main>
      <footer>
        <Brand />
        <p>A recruitment and interview-practice prototype.</p>
        <a href="#how">How it works ↑</a>
      </footer>
    </>
  );
}
