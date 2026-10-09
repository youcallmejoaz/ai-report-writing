import { useState } from "react";
import { getDevUser, setDevUser } from "./api/client";
import CaseList from "./pages/CaseList";
import CaseEvidence from "./pages/CaseEvidence";
import ReportReview from "./pages/ReportReview";
import TemplateAdmin from "./pages/TemplateAdmin";

export type View =
  | { page: "cases" }
  | { page: "evidence"; caseId: string }
  | { page: "report"; reportId: string }
  | { page: "templates" };

const DEV_USERS = ["alice", "aaron", "bob", "carol", "dan", "erin", "sam"];

export default function App() {
  const [view, setView] = useState<View>({ page: "cases" });
  const [user, setUser] = useState(getDevUser());

  return (
    <div className="app">
      <header>
        <strong>Report Workbench</strong>
        <nav>
          <button onClick={() => setView({ page: "cases" })}>Cases</button>
          <button onClick={() => setView({ page: "templates" })}>Templates</button>
        </nav>
        <label className="dev-user">
          Signed in as (local dev only){" "}
          <select
            value={user}
            onChange={(e) => {
              setDevUser(e.target.value);
              setUser(e.target.value);
              setView({ page: "cases" });
            }}
          >
            {DEV_USERS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>
      </header>
      <main key={user}>
        {view.page === "cases" && <CaseList open={(caseId) => setView({ page: "evidence", caseId })} />}
        {view.page === "evidence" && (
          <CaseEvidence caseId={view.caseId} openReport={(reportId) => setView({ page: "report", reportId })} />
        )}
        {view.page === "report" && <ReportReview reportId={view.reportId} />}
        {view.page === "templates" && <TemplateAdmin />}
      </main>
    </div>
  );
}
