import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, apiBlob } from "../api";
import Breadcrumbs from "../components/Breadcrumbs";
import { shortDate } from "../when";
import "../assessment.css";

// The Library: every document the AI reads, in one place. Hiring policies (followed when a job is
// written), skills references (compared with interview answers) and holiday calendars (skipped when
// interviews are planned). Adding, replacing or removing one makes the AI read that kind again by
// itself, in the background.

type LibraryDocument = {
  name: string;
  size: number;
  added_at: string;
  status: "read" | "not_read" | "failed";
  detail: string;
};

export type LibraryKind = {
  kind: "policies" | "skills" | "holidays";
  label: string;
  used_for: string;
  accepts: string[];
  reading: boolean;
  documents: LibraryDocument[];
};

const STATUS: Record<LibraryDocument["status"], { label: string; tone: string }> = {
  read: { label: "Read", tone: "pass" },
  not_read: { label: "Not read yet", tone: "" },
  failed: { label: "Could not be read", tone: "stop" },
};

const size = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

export default function LibraryPage() {
  const [kinds, setKinds] = useState<LibraryKind[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(
    () =>
      api<LibraryKind[]>("/library")
        .then(setKinds)
        .catch((err) => setError(err.message)),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // While a kind is being read again, ask every 3 seconds, so "Reading…" turns into the result.
  const reading = kinds?.some((kind) => kind.reading) ?? false;
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [reading, load]);

  return (
    <>
      <Breadcrumbs items={[{ label: "Dashboard", to: "/" }, { label: "Library" }]} />
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p>The documents the AI reads. Add, replace or remove them here; the AI reads them again by itself.</p>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {!kinds ? (
        <div className="card glass">
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : (
        kinds.map((kind) => <KindCard key={kind.kind} kind={kind} reload={load} />)
      )}
    </>
  );
}

function KindCard({ kind, reload }: { kind: LibraryKind; reload: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function after(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = event.target as HTMLFormElement;
    void after(async () => {
      const body = new FormData();
      body.append("file", file);
      await api(`/library/${kind.kind}`, { method: "POST", body });
      setFile(null);
      form.reset();
    });
  }

  function remove(name: string) {
    if (!window.confirm(`Remove ${name}? The AI will stop using it.`)) return;
    void after(() => api(`/library/${kind.kind}/${encodeURIComponent(name)}`, { method: "DELETE" }));
  }

  function readAgain() {
    void after(() => api(`/library/${kind.kind}/read-again`, { method: "POST" }));
  }

  async function download(name: string) {
    try {
      const url = URL.createObjectURL(await apiBlob(`/library/${kind.kind}/${encodeURIComponent(name)}`));
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="card glass flush library-kind">
      <div className="card-head">
        <div>
          <h2>{kind.label}</h2>
          <p className="muted small">{kind.used_for}</p>
        </div>
        {kind.reading ? (
          <span className="as-step small">
            <span className="as-spinner" aria-hidden="true" />
            Reading…
          </span>
        ) : (
          <button className="button quiet small" type="button" onClick={readAgain} disabled={busy || kind.documents.length === 0}>
            Read again
          </button>
        )}
      </div>

      {kind.documents.length === 0 ? (
        <p className="muted" style={{ padding: "0 22px 12px" }}>
          No documents yet. The AI works without them, but less well.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Document</th>
              <th>What the AI found</th>
              <th>Added</th>
              <th className="right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {kind.documents.map((document) => (
              <tr key={document.name}>
                <td>
                  <button className="link-button" type="button" onClick={() => void download(document.name)}>
                    {document.name}
                  </button>
                  <span className="cell-sub">{size(document.size)}</span>
                </td>
                <td>
                  <span className={`badge ${STATUS[document.status].tone}`}>{STATUS[document.status].label}</span>
                  <span className="cell-sub">{document.detail}</span>
                </td>
                <td className="muted small nowrap">{shortDate(document.added_at)}</td>
                <td className="right">
                  <button className="button quiet small" type="button" onClick={() => remove(document.name)} disabled={busy}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form className="library-add" onSubmit={add}>
        <input
          type="file"
          accept={kind.accepts.map((type) => `.${type.toLowerCase()}`).join(",")}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          aria-label={`Add to ${kind.label}`}
        />
        <button className="button secondary small" type="submit" disabled={busy || !file}>
          {busy ? "Working…" : "Add"}
        </button>
        <span className="muted small">
          {kind.accepts.join(" or ")}, up to 10 MB. A document with the same name is replaced.
        </span>
      </form>
      {error && <p className="error small" style={{ padding: "0 22px 14px", margin: 0 }}>{error}</p>}
    </section>
  );
}
