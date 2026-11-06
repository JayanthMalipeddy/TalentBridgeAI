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
}
createRoot(document.getElementById("root")!).render(<App />);
