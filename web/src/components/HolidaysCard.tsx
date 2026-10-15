import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Holiday, HolidayAnswer, HolidayDocument, HolidayReadResult, ProposedHoliday } from "../types";

const dayText = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });

// Holidays on the Settings page, with RAG over the government calendar PDF:
// - Reading the PDF stores it in small pieces with embeddings, finds the pieces about holiday dates,
//   and the AI lists the holidays from them. Nothing is saved until a person has checked the list.
// - "Ask about holidays" finds the closest pieces and answers from them, showing what it read.
// The interview planner only ever uses the checked, saved list.
export default function HolidaysCard() {
  const [saved, setSaved] = useState<Holiday[]>([]);
  const [documents, setDocuments] = useState<HolidayDocument[]>([]);
  const [showPast, setShowPast] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [read, setRead] = useState<HolidayReadResult | null>(null);
  const [proposed, setProposed] = useState<(ProposedHoliday & { keep: boolean })[] | null>(null);
  const [newDay, setNewDay] = useState("");
  const [newName, setNewName] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<HolidayAnswer | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadDocuments = () => api<HolidayDocument[]>("/holidays/documents").then(setDocuments).catch(() => setDocuments([]));

  useEffect(() => {
    api<Holiday[]>("/holidays").then(setSaved).catch((err) => setError(err.message));
    void loadDocuments();
  }, []);

  async function work(what: string, task: () => Promise<void>) {
    setBusy(what);
    setError("");
    setMessage("");
    try {
      await task();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  const readPdf = () =>
    work("read", async () => {
      if (!file) return;
      const body = new FormData();
      body.append("file", file);
      const result = await api<HolidayReadResult>("/holidays/read-pdf", { method: "POST", body });
      setRead(result);
      // Public holidays start ticked; optional ones (only for some staff) start unticked.
      setProposed(result.holidays.map((h) => ({ ...h, keep: h.kind === "public" })));
      if (result.holidays.length === 0) setMessage("No dates were found in this PDF. You can add the holidays by hand below.");
      void loadDocuments();
    });

  const saveProposed = () =>
    work("save", async () => {
      if (!proposed) return;
      const chosen = proposed.filter((h) => h.keep).map((h) => ({ day: h.day, name: h.name }));
      const result = await api<{ added: number; holidays: Holiday[] }>("/holidays", {
        method: "POST",
        body: JSON.stringify({ source: "pdf", holidays: chosen }),
      });
      setSaved(result.holidays);
      setProposed(null);
      setRead(null);
      setFile(null);
      setMessage(`Saved ${chosen.length} holidays (${result.added} new).`);
    });

  const addOne = (event: FormEvent) => {
    event.preventDefault();
    return work("add", async () => {
      const result = await api<{ added: number; holidays: Holiday[] }>("/holidays", {
        method: "POST",
        body: JSON.stringify({ source: "manual", holidays: [{ day: newDay, name: newName }] }),
      });
      setSaved(result.holidays);
      setNewDay("");
      setNewName("");
    });
  };

  const remove = (holiday: Holiday) =>
    work("remove", async () => {
      await api(`/holidays/${holiday.id}`, { method: "DELETE" });
      setSaved((list) => list.filter((h) => h.id !== holiday.id));
    });

  const forget = (doc: HolidayDocument) =>
    work("forget", async () => {
      await api(`/holidays/documents/${encodeURIComponent(doc.source)}`, { method: "DELETE" });
      await loadDocuments();
    });

  const ask = (event: FormEvent) => {
    event.preventDefault();
    return work("ask", async () => {
      setAnswer(await api<HolidayAnswer>("/holidays/ask", { method: "POST", body: JSON.stringify({ question }) }));
    });
  };

  const today = new Date().toISOString().slice(0, 10);
  const shown = saved.filter((h) => showPast || h.day >= today);

  return (
    <div className="card glass">
      <div className="row between">
        <div>
          <h2>Holidays</h2>
          <p className="muted small">No interview is planned on these days.</p>
        </div>
        <label className="check small">
          <input type="checkbox" checked={showPast} onChange={(event) => setShowPast(event.target.checked)} />
          Show past
        </label>
      </div>

      <div className="holiday-tools">
        <div className="field">
          <label htmlFor="holiday-pdf">Government holiday calendar (PDF)</label>
          <div className="row">
            <input id="holiday-pdf" type="file" accept=".pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <button className="button secondary" onClick={readPdf} disabled={busy !== "" || !file}>
              {busy === "read" ? "Reading… (up to a minute)" : "Read the PDF"}
            </button>
          </div>
          <span className="hint">
            The PDF is stored in pieces for search (RAG). The AI lists the dates; you check them before anything is saved. The government calendar is in Bangla,
            so it is read with OCR, which takes up to a minute.
          </span>
        </div>

        <form className="field" onSubmit={addOne}>
          <label htmlFor="holiday-day">Add one day by hand</label>
          <div className="row">
            <input id="holiday-day" type="date" value={newDay} onChange={(event) => setNewDay(event.target.value)} required />
            <input className="grow" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Name, e.g. Company anniversary" maxLength={200} />
            <button className="button secondary" type="submit" disabled={busy !== "" || !newDay}>
              Add
            </button>
          </div>
        </form>
      </div>

      {proposed && proposed.length > 0 && (
        <div className="proposed">
          <h3>Found in the PDF: please check</h3>
          {read && (
            <p className="muted small">
              {read.source} was cut into {read.chunks_stored} pieces; the {read.chunks_used} closest to "holiday dates" were read. Untick anything that is not a day off for your
              company, then save.
            </p>
          )}
          <ul className="holiday-list">
            {proposed.map((h, index) => (
              <li key={h.day}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={h.keep}
                    onChange={() => setProposed((list) => list && list.map((x, i) => (i === index ? { ...x, keep: !x.keep } : x)))}
                  />
                  <span className="holiday-day">{dayText(h.day)}</span>
                  <span className="grow">{h.name}</span>
                  {h.kind === "optional" && <span className="badge warn tiny">optional</span>}
                </label>
              </li>
            ))}
          </ul>
          <div className="row">
            <button className="button" onClick={saveProposed} disabled={busy !== ""}>
              Save {proposed.filter((h) => h.keep).length} holidays
            </button>
            <button className="button quiet" onClick={() => setProposed(null)} disabled={busy !== ""}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {message && <p className="success">{message}</p>}
      {error && <p className="error">{error}</p>}

      {shown.length === 0 ? (
        <p className="muted">No holidays saved yet. Read the government PDF or add days by hand.</p>
      ) : (
        <ul className="holiday-list">
          {shown.map((h) => (
            <li key={h.id}>
              <span className="holiday-day">{dayText(h.day)}</span>
              <span className="grow">{h.name}</span>
              <span className="muted small">{h.source === "pdf" ? "from PDF" : "by hand"}</span>
              <button className="notice-close" aria-label={`Remove ${h.name}`} onClick={() => remove(h)} disabled={busy !== ""}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="ask-box">
        <h3>Ask about holidays</h3>
        <form className="row" onSubmit={ask}>
          <input className="grow" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Is there a holiday in the week of Eid?" maxLength={300} />
          <button className="button secondary" type="submit" disabled={busy !== "" || question.trim().length < 3}>
            {busy === "ask" ? "Looking…" : "Ask"}
          </button>
        </form>
        {answer && (
          <div className="answer">
            <p>{answer.answer}</p>
            {answer.sources.length > 0 && (
              <details>
                <summary className="muted small">From {answer.sources.length} pieces of the calendar</summary>
                {answer.sources.map((piece, i) => (
                  <blockquote key={i}>
                    <span className="muted small">{piece.source}</span>
                    <br />
                    {piece.text}
                  </blockquote>
                ))}
              </details>
            )}
          </div>
        )}
        {documents.length > 0 && (
          <p className="muted small docs-line">
            Calendars on file:{" "}
            {documents.map((doc) => (
              <span key={doc.source} className="chip">
                {doc.source} · {doc.chunks} pieces
                <button type="button" className="notice-close" aria-label={`Forget ${doc.source}`} onClick={() => forget(doc)}>
                  ×
                </button>
              </span>
            ))}
          </p>
        )}
      </div>
    </div>
  );
}
