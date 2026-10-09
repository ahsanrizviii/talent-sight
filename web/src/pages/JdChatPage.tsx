import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import JobPostView from "../components/JobPostView";
import type { ChatState } from "../types";

type Message = { from: "you" | "ai"; text: string };

function aiMessage(chat: ChatState): string {
  if (chat.status === "failed") return chat.message;
  if (chat.status === "done")
    return chat.blog_url
      ? "Done. The job is saved, published and posted on the blog."
      : "Done. The job is saved and published, but the blog post could not be made.";
  if (chat.kind === "questions")
    return "I need a few more details:\n- " + chat.questions.join("\n- ");
  return "Here is my draft, based on your brief and the company's hiring policies. Approve it, or tell me what to change.";
}

// "[policy-file.md] The paragraph..." -> source and text
function splitPolicy(policy: string): { source: string; text: string } {
  const match = policy.match(/^\[(.+?)\]\s*([\s\S]*)$/);
  return match ? { source: match[1], text: match[2] } : { source: "", text: policy };
}

function PolicySources({ policies }: { policies: string[] }) {
  return (
    <div className="card">
      <h2>Company policy used</h2>
      <p className="muted small">
        The AI searched the company's hiring policies (RAG), found these paragraphs, and wrote the draft to follow them.
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

export default function JdChatPage() {
  const [chat, setChat] = useState<ChatState | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(body: object, shownText: string) {
    setBusy(true);
    setMessages((old) => [...old, { from: "you", text: shownText }]);
    setText("");

    try {
      const next = chat
        ? await api<ChatState>(`/jd-chat/${chat.thread_id}/reply`, {
            method: "POST",
            body: JSON.stringify(body),
          })
        : await api<ChatState>("/jd-chat", {
            method: "POST",
            body: JSON.stringify(body),
          });

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
  }

  const finished = chat?.status === "done" || chat?.status === "failed";
  const waitingForApproval = chat?.status === "waiting" && chat.kind === "draft";

  return (
    <>
      <h1>Write a job with AI</h1>

      <div className="card">
        <p className="muted">
          Describe the role in a few sentences: the level, the main skills and
          the minimum experience.
        </p>

        {messages.map((message, index) => (
          <p key={index} style={{ whiteSpace: "pre-wrap" }}>
            <strong>{message.from === "you" ? "You" : "AI"}:</strong>{" "}
            {message.text}
          </p>
        ))}

        {busy && (
          <p className="muted">The AI is working... this can take up to a minute.</p>
        )}
      </div>

      {waitingForApproval && chat.draft && (
        <div className="card">
          <JobPostView {...chat.draft} />
          <p className="muted">
            Scoring weights: technical skills{" "}
            {chat.draft.weights.technical_skills}%, experience{" "}
            {chat.draft.weights.experience}%, qualifications{" "}
            {chat.draft.weights.qualifications}%, overall match{" "}
            {chat.draft.weights.jd_match}%
          </p>
          <button
            className="button"
            disabled={busy}
            onClick={() => send({ approve: true }, "Approve and publish.")}
          >
            Approve and publish
          </button>
        </div>
      )}

      {waitingForApproval && !!chat.policies?.length && (
        <PolicySources policies={chat.policies} />
      )}

      {chat?.status === "done" && (
        <div className="card row">
          <Link className="button secondary" to={`/jobs/${chat.job_id}`}>
            Open the job profile
          </Link>
          {chat.blog_url && (
            <a
              className="button secondary"
              href={chat.blog_url}
              target="_blank"
              rel="noreferrer"
            >
              View the blog post
            </a>
          )}
        </div>
      )}

      {finished ? (
        <button className="button" onClick={startAgain}>
          Start a new job
        </button>
      ) : (
        <div className="card">
          <div className="field">
            <label htmlFor="message">
              {!chat
                ? "Your brief"
                : waitingForApproval
                ? "Or ask for changes"
                : "Your answer"}
            </label>
            <textarea
              id="message"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <button
            className="button"
            disabled={busy || text.trim().length < (chat ? 1 : 10)}
            onClick={() => send(chat ? { text } : { brief: text }, text)}
          >
            {!chat ? "Start" : waitingForApproval ? "Ask for changes" : "Send"}
          </button>
        </div>
      )}
    </>
  );
}