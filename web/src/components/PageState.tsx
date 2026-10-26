import { Link } from "react-router-dom";

// What a page shows while its data is on the way, and when it could not be loaded (N25).
// A failed page always says what happened and offers a way forward.

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="card glass" role="status" aria-busy="true">
      <span className="sr-only">{label}</span>
      <div className="skeleton" />
      <div className="skeleton" />
    </div>
  );
}

export function LoadError({
  message,
  back = "/",
  backLabel = "Back to the dashboard",
}: {
  message: string;
  back?: string;
  backLabel?: string;
}) {
  return (
    <div className="card glass load-error" role="alert">
      <h2>This page could not be loaded</h2>
      <p>{message}</p>
      <div className="row">
        <button className="button" type="button" onClick={() => window.location.reload()}>
          Try again
        </button>
        <Link className="button secondary" to={back}>
          {backLabel}
        </Link>
      </div>
    </div>
  );
}