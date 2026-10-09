import type { ScoreBreakdown } from "../types";

// The score breakdown panel (WBS 6.5): the total, then each dimension with its weight,
// the points it adds to the total, and the AI's justification.
export default function ScorePanel({ score }: { score: ScoreBreakdown }) {
  return (
    <div className="card">
      <div className="score-head">
        <div>
          <h2>Score</h2>
          <p className="muted small">Weighted total of four dimensions, out of 100.</p>
        </div>
        <div className="score-total">{score.overall}</div>
      </div>

      {score.dimensions.map((d) => (
        <div className="dimension" key={d.dimension}>
          <div className="dimension-head">
            <strong>{d.label}</strong>
            <span className="muted small">
              {d.score}/100 · weight {d.weight}% · adds {d.contribution}
            </span>
          </div>
          <div className="bar">
            <div style={{ width: `${d.score}%` }} />
          </div>
          <p className="small muted">{d.justification}</p>
        </div>
      ))}
    </div>
  );
}