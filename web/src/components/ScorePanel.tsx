import type { ScoreBreakdown } from "../types";

// The score breakdown panel (WBS 6.5): the total, then each dimension with its weight,
// the points it adds to the total, and the AI's justification.
// 70 and above reads as a good fit, 50 to 70 as a maybe, below that as a poor match.
// The block behind the total is tinted to match, so the verdict lands before the number is read.
function tone(overall: number): string {
  if (overall >= 70) return "big-stat";
  if (overall >= 50) return "big-stat warn";
  return "big-stat stop";
}

export default function ScorePanel({ score }: { score: ScoreBreakdown }) {
  return (
    <div className="card glass">
      <div className="score-head">
        <div>
          <h2>Score</h2>
          <p className="muted small">Weighted total of four dimensions, out of 100.</p>
        </div>
        <div className={tone(score.overall)}>
          <strong>{score.overall}</strong>
          <span>out of 100</span>
        </div>
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