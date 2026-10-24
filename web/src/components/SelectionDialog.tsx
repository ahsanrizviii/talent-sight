import { useEffect, useMemo, useState, type ReactNode } from "react";

// Choosing who goes on: by a pass mark, by the top N, or by hand. Used to close an interview round
// and to pick who is selected for onboarding after the report.
//
// The scores decide the order; the hiring team decides the cut. When the top N would cut between two
// people with the same score, the dialog asks which of them go through: it never picks for you.

export type Choice = { id: number; name: string; sub?: string; score: number | null };
export type Rule = "pass_mark" | "top_n" | "manual";

type Props = {
  title: string;
  intro: ReactNode;
  items: Choice[]; // best first; people without a score last
  scoreLabel: string;
  defaultMark?: number;
  passWord: string; // "go to the next round", "are selected for onboarding"
  failWord: string; // "get a rejection e-mail"
  extra?: ReactNode; // more fields: the next round's first day, the first day at work
  extraReady?: boolean; // false while a required extra field is empty
  confirmLabel: (count: number) => string;
  onConfirm: (ids: number[], rule: Rule, value: number | null) => Promise<void>;
  onClose: () => void;
};

export default function SelectionDialog({
  title,
  intro,
  items,
  scoreLabel,
  defaultMark = 60,
  passWord,
  failWord,
  extra,
  extraReady = true,
  confirmLabel,
  onConfirm,
  onClose,
}: Props) {
  const scored = useMemo(() => items.filter((item) => item.score !== null), [items]);
  const [rule, setRule] = useState<Rule>("pass_mark");
  const [mark, setMark] = useState(defaultMark);
  const [top, setTop] = useState(Math.min(5, Math.max(1, scored.length)));
  const [byHand, setByHand] = useState<Set<number>>(new Set());
  const [tiePick, setTiePick] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  // The top N, and the tie at the cut when there is one.
  const cut = useMemo(() => {
    const n = Math.max(0, Math.min(top || 0, scored.length));
    if (n === 0) return { sure: [] as Choice[], tied: [] as Choice[], need: 0 };
    if (n === scored.length) return { sure: scored, tied: [], need: 0 };
    const boundary = scored[n - 1].score;
    if (scored[n].score !== boundary) return { sure: scored.slice(0, n), tied: [], need: 0 };
    const sure = scored.filter((item) => (item.score ?? 0) > (boundary ?? 0));
    const tied = scored.filter((item) => item.score === boundary);
    return { sure, tied, need: n - sure.length };
  }, [scored, top]);

  // A new N means a new tie: the earlier pick no longer applies.
  useEffect(() => setTiePick(new Set()), [top]);

  const chosen: Set<number> = useMemo(() => {
    if (rule === "manual") return byHand;
    if (rule === "pass_mark") return new Set(scored.filter((item) => (item.score ?? 0) >= mark).map((item) => item.id));
    return new Set([...cut.sure.map((item) => item.id), ...tiePick]);
  }, [rule, byHand, scored, mark, cut, tiePick]);

  const tieOpen = rule === "top_n" && cut.tied.length > 0 && tiePick.size !== cut.need;
  const unscored = items.length - scored.length;

  function switchTo(next: Rule) {
    if (next === "manual") setByHand(new Set(chosen)); // start from what the rule picked
    setRule(next);
  }

  function toggle(set: Set<number>, id: number, update: (next: Set<number>) => void, limit?: number) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else if (limit === undefined || next.size < limit) next.add(id);
    update(next);
  }

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const value = rule === "pass_mark" ? mark : rule === "top_n" ? top : null;
      await onConfirm(
        items.filter((item) => chosen.has(item.id)).map((item) => item.id),
        rule,
        value,
      );
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal glass wide" role="dialog" aria-modal="true" aria-labelledby="selection-title" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2 id="selection-title">{title}</h2>
          <button className="notice-close" type="button" aria-label="Close" onClick={onClose} disabled={busy}>
            ×
          </button>
        </div>
        <div className="muted small">{intro}</div>

        <div className="tabs" role="tablist" style={{ marginTop: 12 }}>
          <button role="tab" aria-selected={rule === "pass_mark"} onClick={() => switchTo("pass_mark")}>
            Pass mark
          </button>
          <button role="tab" aria-selected={rule === "top_n"} onClick={() => switchTo("top_n")}>
            Top N
          </button>
          <button role="tab" aria-selected={rule === "manual"} onClick={() => switchTo("manual")}>
            Pick by hand
          </button>
        </div>

        <div className="invite-inputs">
          {rule === "pass_mark" && (
            <div className="field">
              <label htmlFor="pass-mark">{scoreLabel} at least</label>
              <input id="pass-mark" type="number" min={0} max={100} step={0.5} value={mark} onChange={(e) => setMark(Number(e.target.value))} />
            </div>
          )}
          {rule === "top_n" && (
            <div className="field">
              <label htmlFor="top-n">How many of the best</label>
              <input id="top-n" type="number" min={0} max={scored.length} value={top} onChange={(e) => setTop(Number(e.target.value))} />
            </div>
          )}
          {extra}
        </div>

        {tieOpen && (
          <div className="tie-box" role="alert">
            <strong>
              A tie at the cut: {cut.tied.length} people have {cut.tied[0].score}. Pick {cut.need} of them.
            </strong>
            <ul>
              {cut.tied.map((item) => (
                <li key={item.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={tiePick.has(item.id)}
                      onChange={() => toggle(tiePick, item.id, setTiePick, cut.need)}
                    />{" "}
                    {item.name} {item.sub && <span className="muted small">· {item.sub}</span>}
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="modal-table">
          <table>
            <thead>
              <tr>
                <th>{rule === "manual" ? "Pass" : ""}</th>
                <th>Candidate</th>
                <th className="right">{scoreLabel}</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const passes = chosen.has(item.id);
                return (
                  <tr key={item.id} className={passes ? "chosen" : ""}>
                    <td>
                      {rule === "manual" && (
                        <input type="checkbox" checked={passes} onChange={() => toggle(byHand, item.id, setByHand)} aria-label={`Pass ${item.name}`} />
                      )}
                    </td>
                    <td>
                      {item.name}
                      {item.sub && <span className="cell-sub">{item.sub}</span>}
                    </td>
                    <td className="right score-cell">{item.score ?? "—"}</td>
                    <td className="small">{passes ? <span className="success">Passes</span> : <span className="muted">Rejection e-mail</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="small">
          <strong>{chosen.size}</strong> {passWord}. <strong>{items.length - chosen.size}</strong> {failWord}.
          {unscored > 0 && rule !== "manual" && ` ${unscored} without a score pass only if you pick them by hand.`}
        </p>
        {error && <p className="error">{error}</p>}

        <div className="row">
          <button className="button" type="button" disabled={busy || tieOpen || !extraReady} onClick={() => void confirm()}>
            {busy ? "Working…" : confirmLabel(chosen.size)}
          </button>
          <button className="button secondary" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
        <p className="muted small">This cannot be undone: the e-mails go out straight away.</p>
      </div>
    </div>
  );
}
