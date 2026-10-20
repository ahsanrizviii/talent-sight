import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import JobPipeline from "../components/JobPipeline";
import { LoadError, Loading } from "../components/PageState";
import type { Job, JobInput, Weights } from "../types";

const EMPTY_JOB: JobInput = {
  title: "",
  description: "",
  required_skills: [],
  preferred_skills: [],
  qualifications: [],
  min_experience_years: 0,
  selection_criteria: "",
  weights: {
    technical_skills: 40,
    experience: 30,
    qualifications: 15,
    jd_match: 15,
  },
};

const WEIGHT_LABELS: Record<keyof Weights, string> = {
  technical_skills: "Technical skills",
  experience: "Experience",
  qualifications: "Qualifications",
  jd_match: "Overall CV match",
};

type Busy = "" | "save" | "publish" | "delete";

const toLines = (items: string[]) => items.join("\n");
const fromLines = (text: string) => text.split("\n");
const clean = (items: string[]) =>
  items.map((item) => item.trim()).filter(Boolean);

export default function JobFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [job, setJob] = useState<JobInput>(EMPTY_JOB);
  const [saved, setSaved] = useState<Job | null>(null);
  const [loading, setLoading] = useState(!!id); // an existing job is loaded before the form is shown
  const [loadError, setLoadError] = useState("");
  const [dirty, setDirty] = useState(false); // changes on screen that are not saved yet
  const [busy, setBusy] = useState<Busy>("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    api<Job>(`/jobs/${id}`)
      .then((loaded) => {
        setJob(loaded);
        setSaved(loaded);
      })
      .catch((err) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  function change<K extends keyof JobInput>(field: K, value: JobInput[K]) {
    setJob({ ...job, [field]: value });
    setDirty(true);
  }

  function changeWeight(name: keyof Weights, value: number) {
    setJob({ ...job, weights: { ...job.weights, [name]: value } });
    setDirty(true);
  }

  const weightTotal = Object.values(job.weights).reduce(
    (sum, value) => sum + value,
    0
  );

  // Saves what is on screen and returns the saved job.
  async function persist(): Promise<Job> {
    const body = JSON.stringify({
      ...job,
      required_skills: clean(job.required_skills),
      preferred_skills: clean(job.preferred_skills),
      qualifications: clean(job.qualifications),
    });
    const result = id
      ? await api<Job>(`/jobs/${id}`, { method: "PUT", body })
      : await api<Job>("/jobs", { method: "POST", body });
    setSaved(result);
    setDirty(false);
    return result;
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const result = await persist();
      setMessage("Saved.");
      if (!id) navigate(`/jobs/${result.id}`, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function publish() {
    setBusy("publish");
    setError("");
    setMessage("");
    try {
      if (dirty) await persist(); // publish what is on screen, not an older saved version
      const result = await api<Job>(`/jobs/${id}/publish`, { method: "POST" });
      setSaved(result);
      setMessage(
        result.blog_url
          ? "Published and posted on the blog."
          : "Published, but the blog post could not be made. Check the Google settings."
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (!window.confirm("Delete this job and all its candidates? This cannot be undone.")) return;
    setBusy("delete");
    setError("");
    try {
      await api(`/jobs/${id}`, { method: "DELETE" });
      navigate("/jobs");
    } catch (err) {
      setError((err as Error).message);
      setBusy("");
    }
  }

  if (loadError) return <LoadError message={loadError} back="/jobs" backLabel="Back to jobs" />;
  if (loading) return <Loading label="Loading the job…" />;

  return (
    <>
      {saved && <JobPipeline job={saved} />}

      <form className="card" onSubmit={save}>
        <h1>{id ? "Edit job" : "New job"}</h1>

        {id && (
          <p>
            <Link to={`/jobs/${id}/candidates`}>Candidates for this job →</Link>
          </p>
        )}

        {saved?.blog_url && (
          <p>
            Blog post:{" "}
            <a href={saved.blog_url} target="_blank" rel="noreferrer">
              View on blog
            </a>
          </p>
        )}

        <div className="field">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            value={job.title}
            onChange={(e) => change("title", e.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor="required">Required skills (one per line)</label>
          <textarea
            id="required"
            value={toLines(job.required_skills)}
            onChange={(e) => change("required_skills", fromLines(e.target.value))}
          />
        </div>

        <div className="field">
          <label htmlFor="preferred">Preferred skills (one per line)</label>
          <textarea
            id="preferred"
            value={toLines(job.preferred_skills)}
            onChange={(e) =>
              change("preferred_skills", fromLines(e.target.value))
            }
          />
        </div>

        <div className="field">
          <label htmlFor="qualifications">Qualifications (one per line)</label>
          <textarea
            id="qualifications"
            value={toLines(job.qualifications)}
            onChange={(e) =>
              change("qualifications", fromLines(e.target.value))
            }
          />
        </div>

        <div className="field">
          <label htmlFor="experience">Minimum years of experience</label>
          <input
            id="experience"
            type="number"
            min={0}
            max={40}
            value={job.min_experience_years}
            onChange={(e) =>
              change("min_experience_years", Number(e.target.value))
            }
          />
        </div>

        <div className="field">
          <label htmlFor="criteria">Selection criteria</label>
          <textarea
            id="criteria"
            value={job.selection_criteria}
            onChange={(e) => change("selection_criteria", e.target.value)}
          />
        </div>

        <div className="field">
          <label>
            Scoring weights (%) — total {weightTotal}
            {weightTotal !== 100 && (
              <span className="error"> (must be 100)</span>
            )}
          </label>
          <div className="row">
            {(Object.keys(WEIGHT_LABELS) as (keyof Weights)[]).map((name) => (
              <label key={name} className="muted">
                {WEIGHT_LABELS[name]}{" "}
                <input
                  type="number"
                  min={0}
                  max={100}
                  style={{ width: 70 }}
                  value={job.weights[name]}
                  onChange={(e) =>
                    changeWeight(name, Number(e.target.value))
                  }
                />
              </label>
            ))}
          </div>
        </div>

        <div className="field">
          <label htmlFor="description">Job post text</label>
          <textarea
            id="description"
            style={{ minHeight: 220 }}
            value={job.description}
            onChange={(e) => change("description", e.target.value)}
          />
        </div>

        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}
        {dirty && id && !busy && <p className="muted small">You have unsaved changes.</p>}

        <div className="row">
          <button
            className="button"
            type="submit"
            disabled={!!busy || weightTotal !== 100}
          >
            {busy === "save" ? "Saving…" : "Save"}
          </button>
          {id && (
            <button
              className="button secondary"
              type="button"
              onClick={publish}
              disabled={!!busy || weightTotal !== 100}
            >
              {busy === "publish" ? "Publishing…" : dirty ? "Save and publish" : "Publish"}
            </button>
          )}
          {id && (
            <button className="button danger" type="button" onClick={remove} disabled={!!busy}>
              {busy === "delete" ? "Deleting…" : "Delete"}
            </button>
          )}
        </div>
        {busy === "publish" && (
          <p className="muted small busy-note">Posting to the blog can take a few seconds.</p>
        )}
      </form>
    </>
  );
}