import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import Empty from "../components/Empty";
import Icon from "../components/Icon";
import JobPostView from "../components/JobPostView";
import type { ChatHistory, ChatState, ChatSummary } from "../types";
import type { LibraryKind } from "./LibraryPage";
import { shortDateTime } from "../when";

type Message = { from: "you" | "ai"; text: string };

function aiMessage(chat: ChatState): string {
  if (chat.status === "failed") return chat.message;
  if (chat.status === "done")
    return chat.blog_url
      ? "Done. The job is saved, published and posted on the blog."
      : "Done. The job is saved and published, but the blog post could not be made.";
  if (chat.kind === "questions") return "I need a few more details:\n- " + chat.questions.join("\n- ");
  return chat.policies?.length
    ? "Here is my draft, based on your brief and the company's hiring policies. Approve it, or tell me what to change."
    : "Here is my draft, based on your brief. No company hiring policies are loaded. Approve it, or tell me what to change.";
}

// "[policy-file.md] The paragraph..." -> source and text
function splitPolicy(policy: string): { source: string; text: string } {
  const match = policy.match(/^\[(.+?)\]\s*([\s\S]*)$/);
  return match ? { source: match[1], text: match[2] } : { source: "", text: policy };
}

function PolicySources({ policies }: { policies: string[] }) {
  return (
    <div className="card glass">
      <h2>Company policy used</h2>
      <p className="muted small">
        The AI searched the company's hiring policies, found these paragraphs, and wrote the draft to follow them.
      </p>
      <ul className="policies">
        {policies.map((policy, index) => {
          const { source, text } = splitPolicy(policy);
          return (
            <li key={index}>
              {source && <span className="badge">{source}</span>}
              <span className="small">{text}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// Reading a chat that happened earlier. Every job written with the AI keeps its conversation,
// so anyone can see what was asked for and what the AI asked back.
function PastChat({ threadId }: { threadId: string }) {
  const [chat, setChat] = useState<ChatHistory | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<ChatHistory>(`/jd-chat/${threadId}/history`)
      .then(setChat)
      .catch((err) => setError(err.message));
  }, [threadId]);

  if (error) return <p className="error">{error}</p>;
  if (!chat) return <div className="card glass"><div className="skeleton" /><div className="skeleton" /></div>;

  return (
    <>
      <Link className="back-link" to="/jd-chat">
        <Icon name="back" />
        All chats
      </Link>

      <div className="page-head">
        <div>
          <h1>{chat.title}</h1>
          <p>
            {shortDateTime(chat.created_at)} · {chat.lines.length} messages
          </p>
        </div>
        <div className="row">
          {chat.job_id && (
            <Link className="button secondary" to={`/jobs/${chat.job_id}`}>
              Open the job profile
            </Link>
          )}
          <Link className="button" to="/jd-chat">
            <Icon name="sparkle" />
            Write another
          </Link>
        </div>
      </div>

      <div className="card glass">
        <div className="chat-log">
          {chat.lines.map((line, index) => (
            <div className={`chat-line ${line.role}`} key={index}>
              <span className="chat-who">{line.role === "recruiter" ? "You" : "TalentSight AI"}</span>
              <span className="chat-text">{line.text}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// Writing a job description with the AI, and the record of every chat that came before.
export default function JdChatPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const [chat, setChat] = useState<ChatState | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [past, setPast] = useState<ChatSummary[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // The hiring-policy documents in the Library, and the ones this job must follow (all, unless untick).
  const [policyFiles, setPolicyFiles] = useState<string[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);

  useEffect(() => {
    api<ChatSummary[]>("/jd-chat").then(setPast).catch(() => undefined);
  }, [threadId, chat?.status]);

  useEffect(() => {
    api<LibraryKind[]>("/library")
      .then((kinds) => {
        const names = (kinds.find((kind) => kind.kind === "policies")?.documents ?? [])
          .filter((document) => document.status === "read")
          .map((document) => document.name);
        setPolicyFiles(names);
        setChosen(names);
      })
      .catch(() => undefined);
  }, []);

  if (threadId) return <PastChat threadId={threadId} />;

  async function send(body: object, shownText: string) {
    setBusy(true);
    setMessages((old) => [...old, { from: "you", text: shownText }]);
    setText("");

    try {
      const next = chat
        ? await api<ChatState>(`/jd-chat/${chat.thread_id}/reply`, { method: "POST", body: JSON.stringify(body) })
        : await api<ChatState>("/jd-chat", { method: "POST", body: JSON.stringify(body) });

      setChat(next);
      setMessages((old) => [...old, { from: "ai", text: aiMessage(next) }]);
    } catch (err) {
      setMessages((old) => [...old, { from: "ai", text: (err as Error).message }]);
    } finally {
      setBusy(false);
    }
  }

  function startAgain() {
    setChat(null);
    setMessages([]);
    setChosen(policyFiles);
  }

  function toggle(name: string) {
    setChosen((old) => (old.includes(name) ? old.filter((item) => item !== name) : [...old, name]));
  }

  // Every document ticked is sent as [] ("all"), so a policy added to the Library later is used too.
  const policySources = chosen.length === policyFiles.length ? [] : chosen;
  const noPolicyChosen = policyFiles.length > 0 && chosen.length === 0;

  const finished = chat?.status === "done" || chat?.status === "failed";
  const waitingForApproval = chat?.status === "waiting" && chat.kind === "draft";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Write a job with AI</h1>
          <p>Describe the role in a few sentences: the level, the main skills and the minimum experience.</p>
        </div>
      </div>

      {messages.length > 0 && (
        <div className="card glass">
          <div className="chat-log">
            {messages.map((message, index) => (
              <div className={`chat-line ${message.from === "you" ? "recruiter" : "assistant"}`} key={index}>
                <span className="chat-who">{message.from === "you" ? "You" : "TalentSight AI"}</span>
                <span className="chat-text">{message.text}</span>
              </div>
            ))}
          </div>
          {busy && <p className="muted small" style={{ marginTop: 14, marginBottom: 0 }}>Thinking… this can take up to a minute.</p>}
        </div>
      )}

      {waitingForApproval && chat.draft && (
        <div className="card glass">
          <JobPostView {...chat.draft} />
          <p className="muted small">
            Scoring weights: technical skills {chat.draft.weights.technical_skills}%, experience{" "}
            {chat.draft.weights.experience}%, qualifications {chat.draft.weights.qualifications}%, overall match{" "}
            {chat.draft.weights.jd_match}%
          </p>
          {!!chat.draft.interview_rounds?.length && (
            <p className="muted small">
              Hiring process:{" "}
              {chat.draft.interview_rounds
                .map(
                  (round, index) =>
                    `${index + 1}. ${round.name} [${round.type === "hr" ? "HR" : "Technical"}]${round.focus ? ` (${round.focus})` : ""}`,
                )
                .join(" · ")}
            </p>
          )}
          <button className="button" disabled={busy} onClick={() => send({ approve: true }, "Approve and publish.")}>
            Approve and publish
          </button>
        </div>
      )}

      {waitingForApproval && !!chat.policies?.length && <PolicySources policies={chat.policies} />}

      {chat?.status === "done" && (
        <div className="card row">
          <Link className="button secondary" to={`/jobs/${chat.job_id}`}>
            Open the job profile
          </Link>
          {chat.blog_url && (
            <a className="button secondary" href={chat.blog_url} target="_blank" rel="noreferrer">
              <Icon name="external" />
              View the blog post
            </a>
          )}
        </div>
      )}

      {finished ? (
        <button className="button" onClick={startAgain}>
          Write another job
        </button>
      ) : (
        <div className="card glass">
          <div className="field">
            <label htmlFor="message">
              {!chat ? "Your brief" : waitingForApproval ? "Or ask for changes" : "Your answer"}
            </label>
            <textarea id="message" value={text} onChange={(event) => setText(event.target.value)} />
          </div>
          {!chat && policyFiles.length > 0 && (
            <fieldset className="policy-pick">
              <legend>Company policies the AI must follow</legend>
              {policyFiles.map((name) => (
                <label key={name}>
                  <input type="checkbox" checked={chosen.includes(name)} onChange={() => toggle(name)} />
                  {name}
                </label>
              ))}
              <span className="hint">
                {noPolicyChosen ? "Tick at least one policy document." : "Add or replace policy documents on the "}
                {!noPolicyChosen && <Link to="/library">Library page</Link>}
                {!noPolicyChosen && "."}
              </span>
            </fieldset>
          )}
          <button
            className="button"
            disabled={busy || text.trim().length < (chat ? 1 : 10) || (!chat && noPolicyChosen)}
            onClick={() => send(chat ? { text } : { brief: text, policy_sources: policySources }, text)}
          >
            {!chat ? "Start" : waitingForApproval ? "Ask for changes" : "Send"}
          </button>
        </div>
      )}

      <div className="card glass flush">
        <div className="card-head">
          <h2>Earlier chats</h2>
          <span className="result-count">{past.length}</span>
        </div>
        {past.length === 0 ? (
          <Empty title="No chats yet">Every job you write with the AI is kept here, so you can read back how it was decided.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Role</th>
                <th>State</th>
                <th>Messages</th>
                <th>Last change</th>
                <th className="right">Job</th>
              </tr>
            </thead>
            <tbody>
              {past.map((item) => (
                <tr key={item.thread_id}>
                  <td>
                    <button
                      className="button quiet small"
                      style={{ padding: 0 }}
                      onClick={() => navigate(`/jd-chat/${item.thread_id}`)}
                    >
                      {item.title}
                    </button>
                  </td>
                  <td>
                    <span
                      className={
                        item.status === "done" ? "badge pass" : item.status === "failed" ? "badge stop" : "badge warn"
                      }
                    >
                      {item.status === "done" ? "Published" : item.status === "failed" ? "Failed" : "Unfinished"}
                    </span>
                  </td>
                  <td className="muted num">{item.messages}</td>
                  <td className="muted small nowrap">{shortDateTime(item.updated_at)}</td>
                  <td className="right">
                    {item.job_id ? <Link to={`/jobs/${item.job_id}`}>Open</Link> : <span className="muted">—</span>}
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
