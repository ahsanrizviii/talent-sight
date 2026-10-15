import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import RescheduleBox from "../components/RescheduleBox";
import type { CandidateRow, InviteBatch, InvitePlan, Job, PlanRules } from "../types";

const dayText = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const timeText = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function tomorrow(): string {
  const day = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

// Moves one item of a list up (-1) or down (+1).
function moved<T>(list: T[], index: number, step: -1 | 1): T[] {
  const next = [...list];
  const other = index + step;
  if (other < 0 || other >= next.length) return list;
  [next[index], next[other]] = [next[other], next[index]];
  return next;
}

// After screening: the ranked shortlist with scores, and one action that books and e-mails many
// candidates at once. HR takes the top N or picks people in their own order, sees the plan,
// can still move people up or down or untick them, then sends.
export default function InvitePage() {
  const { id } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [ranked, setRanked] = useState<CandidateRow[]>([]);
  const [rules, setRules] = useState<PlanRules | null>(null);
  const [mode, setMode] = useState<"top" | "pick">("top");
  const [top, setTop] = useState(5);
  const [picked, setPicked] = useState<number[]>([]);
  const [minutes, setMinutes] = useState(60);
  const [startDate, setStartDate] = useState(tomorrow);
  const [plan, setPlan] = useState<InvitePlan | null>(null);
  const [order, setOrder] = useState<number[]>([]); // candidate ids in the plan, first = earliest time
  const [unticked, setUnticked] = useState<Set<number>>(new Set());
  const [batch, setBatch] = useState<InviteBatch | null>(null);
  const [moving, setMoving] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadBatch = useCallback(() => api<InviteBatch | null>(`/jobs/${id}/invite-batches/latest`).then(setBatch), [id]);
  const loadRanked = useCallback(
    () => api<CandidateRow[]>(`/jobs/${id}/candidates`).then((rows) => setRanked(rows.filter((r) => r.status === "screened"))),
    [id],
  );

  useEffect(() => {
    api<Job>(`/jobs/${id}`).then(setJob).catch((err) => setError(err.message));
    loadRanked().catch((err) => setError(err.message));
    api<PlanRules>(`/jobs/${id}/invite-plan/rules`)
      .then((found) => {
        setRules(found);
        setMinutes(found.interview_minutes);
      })
      .catch(() => setRules(null));
    loadBatch().catch(() => undefined);
  }, [id, loadBatch, loadRanked]);

  // While e-mails are still going out, check every two seconds.
  useEffect(() => {
    if (!batch || batch.queued === 0) return;
    const timer = window.setInterval(() => loadBatch().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [batch, loadBatch]);

  async function makePlan(event?: FormEvent) {
    event?.preventDefault();
    setBusy(true);
    setError("");
    try {
      const who = mode === "top" ? { top } : { candidate_ids: picked };
      const made = await api<InvitePlan>(`/jobs/${id}/invite-plan`, {
        method: "POST",
        body: JSON.stringify({ ...who, start_date: startDate, duration_minutes: minutes }),
      });
      setPlan(made);
      setOrder(made.slots.map((s) => s.candidate_id));
      setUnticked(new Set());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // The times stay in place (earliest first); moving a person up gives them an earlier time.
  const times = plan ? plan.slots.map((s) => s.scheduled_at) : [];
  const slotOf = (candidateId: number) => plan?.slots.find((s) => s.candidate_id === candidateId);
  const rows = order.map((candidateId, index) => ({ ...slotOf(candidateId)!, scheduled_at: times[index] }));
  const chosen = rows.filter((r) => !unticked.has(r.candidate_id));
  const days = new Set(chosen.map((r) => new Date(r.scheduled_at).toDateString())).size;

  async function send() {
    if (!plan) return;
    const items = chosen.map((r) => ({ candidate_id: r.candidate_id, scheduled_at: r.scheduled_at }));
    if (!window.confirm(`Book ${items.length} interviews and e-mail ${items.length} candidates now? This cannot be undone.`)) return;
    setBusy(true);
    setError("");
    try {
      setBatch(await api<InviteBatch>(`/jobs/${id}/invite-batches`, { method: "POST", body: JSON.stringify({ items, duration_minutes: minutes }) }));
      setPlan(null);
      setPicked([]);
      await loadRanked();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!batch) return;
    setBusy(true);
    try {
      setBatch(await api<InviteBatch>(`/jobs/${id}/invite-batches/${batch.id}/retry`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const togglePick = (candidateId: number) =>
    setPicked((list) => (list.includes(candidateId) ? list.filter((x) => x !== candidateId) : [...list, candidateId]));
  const toggleTick = (candidateId: number) =>
    setUnticked((old) => {
      const next = new Set(old);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });

  const nameOf = (candidateId: number) => {
    const row = ranked.find((r) => r.id === candidateId);
    return row ? `#${row.rank} ${row.name || row.cv_filename}` : `Candidate ${candidateId}`;
  };
  const howMany = mode === "top" ? Math.min(top, ranked.length) : picked.length;
  const inTop = (c: CandidateRow) => (mode === "top" ? c.rank !== null && c.rank <= howMany : picked.includes(c.id));

  return (
    <>
      <Link className="back-link" to={`/jobs/${id}/candidates`}>
        <Icon name="back" />
        Back to the job
      </Link>

      <div className="page-head">
        <div>
          <h1>Invite top candidates</h1>
          <p>
            {job?.title ?? "Job"} · {ranked.length} passed screening
          </p>
        </div>
      </div>

      {error && <div className="notice stop">{error}</div>}

      {batch && (
        <BatchProgress
          batch={batch}
          busy={busy}
          onRetry={retry}
          moving={moving}
          setMoving={setMoving}
          onMoved={() => loadBatch().catch(() => undefined)}
        />
      )}

      <div className="invite-layout">
        <form className="card glass" onSubmit={makePlan}>
          <h2>Who to invite</h2>
          <label className="check choice">
            <input type="radio" name="mode" checked={mode === "top"} onChange={() => setMode("top")} />
            The top
            <input className="small-number" type="number" min={1} max={500} value={top} onChange={(e) => setTop(Number(e.target.value))} onFocus={() => setMode("top")} aria-label="How many candidates" />
            candidates
          </label>
          <label className="check choice">
            <input type="radio" name="mode" checked={mode === "pick"} onChange={() => setMode("pick")} />
            People I choose, in my order
          </label>

          {mode === "pick" && (
            <>
              <p className="muted small">Tick people in the list. The first one gets the earliest time; use the arrows to change the order.</p>
              {picked.length === 0 ? (
                <p className="muted small">Nobody picked yet.</p>
              ) : (
                <ol className="order-list">
                  {picked.map((candidateId, index) => (
                    <li key={candidateId}>
                      <span className="grow">{nameOf(candidateId)}</span>
                      <span className="move-buttons">
                        <button type="button" aria-label="Earlier" disabled={index === 0} onClick={() => setPicked((l) => moved(l, index, -1))}>
                          ↑
                        </button>
                        <button type="button" aria-label="Later" disabled={index === picked.length - 1} onClick={() => setPicked((l) => moved(l, index, 1))}>
                          ↓
                        </button>
                        <button type="button" aria-label="Remove" onClick={() => togglePick(candidateId)}>
                          ×
                        </button>
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}

          <div className="schedule-grid">
            <div className="field">
              <label htmlFor="first-day">First interview day</label>
              <input id="first-day" type="date" value={startDate} min={tomorrow()} onChange={(e) => setStartDate(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="batch-length">Interview length</label>
              <select id="batch-length" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {[...new Set([30, 45, 60, 90, rules?.interview_minutes ?? 60])].sort((a, b) => a - b).map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </div>
          </div>

          {rules && (
            <p className="rules-note">
              Interviews are booked on {rules.work_days.join(", ")}, {rules.windows.join(" and ")}, with {rules.gap_minutes} minutes between them. {rules.holidays_ahead}{" "}
              holidays ahead are skipped. Change these in <Link to="/settings">Settings</Link>. Times never clash with interviews already booked.
            </p>
          )}

          <button className="button" type="submit" disabled={busy || howMany === 0}>
            Make the plan for {howMany}
          </button>
        </form>

        <div className="card glass flush">
          {ranked.length === 0 ? (
            <Empty title="No shortlist yet">Run the screening on the job page first.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  {mode === "pick" && <th></th>}
                  <th>#</th>
                  <th>Candidate</th>
                  <th className="right">Score</th>
                  <th>Requirements</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((c) => (
                  <tr key={c.id} className={inTop(c) ? "in-top" : ""}>
                    {mode === "pick" && (
                      <td>
                        <input type="checkbox" className="tick" checked={picked.includes(c.id)} onChange={() => togglePick(c.id)} aria-label={`Pick ${c.name}`} />
                      </td>
                    )}
                    <td className="muted num">{c.rank}</td>
                    <td>
                      <Link to={`/candidates/${c.id}`}>{c.name || c.cv_filename}</Link>
                      <span className="cell-sub">{c.email || "no e-mail address"}</span>
                    </td>
                    <td className="right score-cell">{c.overall ?? "—"}</td>
                    <td>
                      <span className="verdict-counts">
                        <span className="verdict-met">{c.met} met</span>
                        <span className="verdict-partially_met">{c.partially_met} partly</span>
                        <span className="verdict-unmet">{c.unmet} unmet</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {plan && (
        <div className="card glass">
          <div className="row between">
            <div>
              <h2>The plan</h2>
              <p className="muted small">
                {chosen.length} interviews of {minutes} minutes over {days} {days === 1 ? "day" : "days"}
                {chosen.length > 0 && `, ${dayText(chosen[0].scheduled_at)} to ${dayText(chosen[chosen.length - 1].scheduled_at)}`}. Use the arrows to give someone an earlier
                or later time. Nothing is booked or sent until you press Send.
              </p>
            </div>
            <div className="row">
              <button className="button quiet" onClick={() => makePlan()} disabled={busy}>
                Make it again
              </button>
              <button className="button" onClick={send} disabled={busy || chosen.length === 0}>
                Send {chosen.length} invitations
              </button>
            </div>
          </div>

          {plan.skipped.length > 0 && (
            <div className="notice">Left out: {plan.skipped.map((s) => `#${s.rank} ${s.name} (${s.reason.toLowerCase().replace(/\.$/, "")})`).join(", ")}.</div>
          )}
          {plan.not_placed > 0 && <div className="notice stop">{plan.not_placed} candidates could not get a slot within a year. Invite fewer people.</div>}
          {unticked.size > 0 && <p className="muted small">Unticked candidates get no invitation. Their times stay empty; make the plan again to close the gaps.</p>}

          <table>
            <thead>
              <tr>
                <th></th>
                <th>Order</th>
                <th>Candidate</th>
                <th>Date</th>
                <th>Time</th>
                <th className="right">Score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, index) => (
                <tr key={r.candidate_id} className={unticked.has(r.candidate_id) ? "dimmed" : ""}>
                  <td>
                    <input type="checkbox" className="tick" checked={!unticked.has(r.candidate_id)} onChange={() => toggleTick(r.candidate_id)} aria-label={`Invite ${r.name}`} />
                  </td>
                  <td>
                    <span className="move-buttons">
                      <button type="button" aria-label="Earlier time" disabled={index === 0} onClick={() => setOrder((l) => moved(l, index, -1))}>
                        ↑
                      </button>
                      <button type="button" aria-label="Later time" disabled={index === rows.length - 1} onClick={() => setOrder((l) => moved(l, index, 1))}>
                        ↓
                      </button>
                    </span>
                  </td>
                  <td>
                    <span className="muted">#{r.rank}</span> {r.name}
                    {r.email_ok ? <span className="cell-sub">{r.email}</span> : <span className="cell-sub warn-text">No usable e-mail: the link must be sent by hand</span>}
                  </td>
                  <td className="nowrap">{dayText(r.scheduled_at)}</td>
                  <td className="nowrap">{timeText(r.scheduled_at)}</td>
                  <td className="right score-cell">{r.overall ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

type ProgressProps = {
  batch: InviteBatch;
  busy: boolean;
  onRetry: () => void;
  moving: number | null;
  setMoving: (sessionId: number | null) => void;
  onMoved: () => void;
};

// The last batch: how many e-mails went out, who failed, and a Reschedule button for each
// interview, for when a candidate asks for another time.
function BatchProgress({ batch, busy, onRetry, moving, setMoving, onMoved }: ProgressProps) {
  const done = batch.sent + batch.failed;
  const failed = batch.deliveries.filter((d) => d.status === "failed");
  return (
    <div className="card glass">
      <div className="row between">
        <div>
          <h2>{batch.queued > 0 ? "Sending the invitations…" : "Invitations sent"}</h2>
          <p className="muted small">
            {new Date(batch.created_at).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })} · {batch.sent} sent
            {batch.failed > 0 && ` · ${batch.failed} not sent`}
            {batch.queued > 0 && ` · ${batch.queued} waiting`}
          </p>
        </div>
        <div className="row">
          {failed.length > 0 && batch.queued === 0 && (
            <button className="button secondary" onClick={onRetry} disabled={busy}>
              Try again for {failed.length}
            </button>
          )}
          <Link className="button secondary" to="/interviews">
            See all interviews
          </Link>
        </div>
      </div>
      <div className="progress" aria-label="Sending progress">
        <div style={{ width: `${batch.total ? (100 * done) / batch.total : 0}%` }} />
      </div>

      <table>
        <thead>
          <tr>
            <th>Candidate</th>
            <th>Date</th>
            <th>Time</th>
            <th>E-mail</th>
            <th className="right"></th>
          </tr>
        </thead>
        <tbody>
          {batch.deliveries.map((d) => (
            <FragmentRow key={d.session_id} d={d} moving={moving} setMoving={setMoving} onMoved={onMoved} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FragmentRow({
  d,
  moving,
  setMoving,
  onMoved,
}: {
  d: InviteBatch["deliveries"][number];
  moving: number | null;
  setMoving: (sessionId: number | null) => void;
  onMoved: () => void;
}) {
  const open = moving === d.session_id;
  return (
    <>
      <tr>
        <td>
          <Link to={`/candidates/${d.candidate_id}`}>{d.name}</Link>
          <span className="cell-sub">{d.email || "no e-mail address"}</span>
        </td>
        <td className="nowrap">{dayText(d.scheduled_at)}</td>
        <td className="nowrap">{timeText(d.scheduled_at)}</td>
        <td className="small">
          {d.status === "sent" ? <span className="badge pass">Sent</span> : d.status === "queued" ? <span className="badge">Waiting</span> : <span className="badge stop">Not sent</span>}
          {d.error && <span className="cell-sub">{d.error}</span>}
        </td>
        <td className="right">
          {d.interview_status === "scheduled" && (
            <button className="button secondary small" onClick={() => setMoving(open ? null : d.session_id)}>
              {open ? "Close" : "Reschedule"}
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="reschedule-row">
          <td colSpan={5}>
            <RescheduleBox
              sessionId={d.session_id}
              currentAt={d.scheduled_at}
              durationMinutes={d.duration_minutes}
              onMoved={onMoved}
              onClose={() => setMoving(null)}
            />
          </td>
        </tr>
      )}
    </>
  );
}
