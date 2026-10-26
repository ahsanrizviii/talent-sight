import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import Empty from "./Empty";
import { CHECK_LABELS, CHECK_TONES } from "../checkStates";
import type { OnboardingRow } from "../types";
import { shortDate } from "../when";

// The Onboarding stage of a job: everyone selected after the report, with the state of their
// first-day identity check. The check itself is done on the Identity check page.
export default function OnboardingStage({ jobId }: { jobId: string }) {
  const [rows, setRows] = useState<OnboardingRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<OnboardingRow[]>(`/jobs/${jobId}/onboarding`)
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [jobId]);

  const verified = (rows ?? []).filter((row) => row.check_state === "verified").length;

  return (
    <>
      <div className="card glass round-head">
        <div>
          <h2 style={{ margin: 0 }}>Onboarding</h2>
          <p className="small" style={{ margin: "4px 0 0" }}>
            {rows ? `${rows.length} selected · ${verified} verified on their first day` : "Loading…"}
          </p>
        </div>
        <Link className="button secondary" to={`/identity?job_id=${jobId}`}>
          Open the identity check
        </Link>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card glass flush">
        {rows === null ? (
          <div style={{ padding: 18 }}>
            <div className="skeleton" />
          </div>
        ) : rows.length === 0 ? (
          <Empty title="Nobody selected yet">Select candidates for onboarding in the Report stage.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>New hire</th>
                <th className="right">Report score</th>
                <th>Selected</th>
                <th>First day</th>
                <th>Face check</th>
                <th className="right"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.candidate_id}>
                  <td>
                    <Link to={`/candidates/${row.candidate_id}?tab=report`}>{row.name}</Link>
                    <span className="cell-sub">{row.email}</span>
                  </td>
                  <td className="right score-cell">{row.report_score ?? "—"}</td>
                  <td className="muted">{shortDate(row.selected_at)}</td>
                  <td className="muted">{row.onboarding_date ? shortDate(row.onboarding_date) : "Not set"}</td>
                  <td>
                    <span className={`badge ${CHECK_TONES[row.check_state]}`}>{CHECK_LABELS[row.check_state]}</span>
                    {row.checked_at && <span className="cell-sub">{shortDate(row.checked_at)}</span>}
                  </td>
                  <td className="right">
                    <Link className="button secondary small" to={`/identity?candidate=${row.candidate_id}`}>
                      {row.check_state === "verified" ? "See the check" : "Check now"}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
