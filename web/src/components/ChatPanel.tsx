import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { api } from "../api";
import type { InterviewChatMessage, ChatSource, ChatTurn } from "../types";

// The question chat beside the transcript in the interview room (Module 13). Interviewer only:
// the API checks the login, and the candidate's page never loads it (N9).
// Each suggested question shows the CV line, transcript moment or requirement it is based on.

const STARTERS = [
  "What should I ask next?",
  "Which requirements have we not covered yet?",
  "How can I check their strongest CV claim?",
];

export default function ChatPanel({ sessionId }: { sessionId: number }) {
  const [messages, setMessages] = useState<InterviewChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(""); // the message being answered right now
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<InterviewChatMessage[]>(`/interviews/${sessionId}/chat`)
      .then(setMessages)
      .catch((err) => setError(err.message))
      .finally(() => setLoaded(true));
  }, [sessionId]);

  // Keep the newest message in view.
  useLayoutEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [messages, pending]);

  async function send(message: string) {
    const clean = message.trim();
    if (!clean || pending) return;
    setPending(clean);
    setError("");
    setText("");
    try {
      const turn = await api<ChatTurn>(`/interviews/${sessionId}/chat`, {
        method: "POST",
        body: JSON.stringify({ message: clean }),
      });
      setMessages((old) => [...old, turn.question, turn.answer]);
    } catch (err) {
      setError((err as Error).message);
      setText(clean); // nothing was saved, so the message comes back for another try
    } finally {
      setPending("");
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(text);
    }
  }

  async function copy(question: string) {
    try {
      await navigator.clipboard.writeText(question);
      setCopied(question);
      window.setTimeout(() => setCopied(""), 1500);
    } catch {
      // Copying is only a convenience; the question stays on screen either way.
    }
  }

  return (
    <section className="card glass chat">
      <div className="transcript-head">
        <h2>Question chat</h2>
        <span className="muted small">Only you see this</span>
      </div>

      <div className="chat-box" ref={box}>
        {!loaded && <p className="muted small">Loading the chat…</p>}
        {loaded && messages.length === 0 && !pending && (
          <div className="chat-empty">
            <p className="muted small">
                Ask me anything about this interview. I can see the CV, the job requirements and the transcript so far.
            </p>
            <div className="chat-starters">
              {STARTERS.map((starter) => (
                <button key={starter} type="button" className="button secondary small" onClick={() => void send(starter)}>
                  {starter}
                </button>
              ))}
            </div>
          </div>
        )}

        <ul className="chat-list">
          {messages.map((message) => (
            <li key={message.id} className={`chat-msg ${message.role}`}>
              <p className="chat-text">{message.text}</p>
              {message.suggestions.length > 0 && (
                <ol className="chat-suggestions">
                  {message.suggestions.map((suggestion, i) => (
                    <li key={i} className="chat-suggestion">
                      <p className="chat-question">{suggestion.question}</p>
                      {suggestion.why && <p className="chat-why">{suggestion.why}</p>}
                      <p className="chat-source">{sourceText(suggestion.source)}</p>
                      <button type="button" className="chat-copy" onClick={() => void copy(suggestion.question)}>
                        {copied === suggestion.question ? "Copied" : "Copy question"}
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </li>
          ))}
          {pending && (
            <>
              <li className="chat-msg interviewer pending">
                <p className="chat-text">{pending}</p>
              </li>
              <li className="chat-msg assistant pending">
                <p className="chat-text muted">Thinking…</p>
              </li>
            </>
          )}
        </ul>
      </div>

      {error && <p className="error small">{error}</p>}
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          void send(text);
        }}
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          maxLength={1000}
          rows={2}
          placeholder="Ask anything about this interview… (Enter sends, Shift+Enter for a new line)"
          aria-label="Message to the question chat"
        />
        <button className="button" type="submit" disabled={!!pending || !text.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}

function sourceText(source: ChatSource): string {
  if (source.kind === "transcript") {
    const who = source.speaker === "interviewer" ? "You" : "Candidate";
    return `Based on: ${who} at ${source.at}, “${source.text}”`;
  }
  if (source.kind === "requirement") return `Based on the job requirement: ${source.text}`;
  return `Based on the CV: ${source.text}`;
}