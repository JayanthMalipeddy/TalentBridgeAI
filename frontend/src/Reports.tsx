import { useState } from "react";
import type { Evidence, Report } from "./contracts";
export function EvidenceList({ items }: { items: Evidence[] }) {
  return (
    <div>
      {items.map((e, i) => (
        <details key={i}>
          <summary>
            {e.source_type} · {e.locator || e.source_id}
          </summary>
          <blockquote>{e.excerpt}</blockquote>
          <small>
            Source: {e.source_id} · {e.locator}
          </small>
        </details>
      ))}
    </div>
  );
}
export function ReportView({
  report,
  approve,
  busy = false,
}: {
  report: Report;
  approve: () => void;
  busy?: boolean;
}) {
  const [message, setMessage] = useState("");
  return (
    <article className="report">
      <p className="eyebrow">
        {report.mode === "mock"
          ? "PRIVATE PRACTICE FEEDBACK"
          : "RECRUITMENT REPORT"}{" "}
        · {report.approval_status}
      </p>
      <h2>
        {report.mode === "mock"
          ? "Your next step forward."
          : "A report grounded in evidence."}
      </h2>
      <p>{report.summary}</p>
      {[
        ["Strengths", report.strengths],
        [report.mode === "mock" ? "Areas to improve" : "Gaps", report.gaps],
        ["Next steps and exercises", report.suggested_next_steps],
      ].map(([title, items]) => (
        <section key={title as string}>
          <h3>{title as string}</h3>
          <ul>
            {(items as string[]).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </section>
      ))}
      <h3>Supporting evidence</h3>
      <EvidenceList items={report.evidence} />
      {report.learning_resources.length > 0 && (
        <>
          <h3>Learning resources</h3>
          {report.learning_resources.map((r, i) => (
            <p key={i}>
              {/^https?:\/\//i.test(r.url) ? (
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title} ↗
                </a>
              ) : (
                r.title
              )}
            </p>
          ))}
        </>
      )}
      {report.mode === "recruitment" && report.draft_email && (
        <>
          <h3>Draft client email</h3>
          <p className="email">{report.draft_email}</p>
        </>
      )}
      <p>Report version: {report.report_version}</p>
      <div className="actions">
        {report.mode === "recruitment" && (
          <button
            disabled={busy || report.approval_status === "approved"}
            onClick={approve}
          >
            Approve report
          </button>
        )}
        <button className="secondary" onClick={() => window.print()}>
          Print / Save as PDF
        </button>
        {report.mode === "recruitment" && report.draft_email && (
          <button
            className="secondary"
            onClick={() =>
              navigator.clipboard
                .writeText(report.draft_email!)
                .then(() => setMessage("Draft copied."))
                .catch(() =>
                  setMessage(
                    "Copy unavailable. Select the draft text to copy it.",
                  ),
                )
            }
          >
            Copy draft email
          </button>
        )}
        {report.mode === "mock" && (
          <a className="button" href="/app/new">
            Start another practice interview
          </a>
        )}
      </div>
      <p role="status">{message}</p>
    </article>
  );
}
