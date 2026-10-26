import { clearToken, getToken } from "./auth";

// The one function every page uses to call the API.
// It adds "/api" in front, sends the login token, sends and reads JSON,
// and turns every failure into a sentence a non-technical user can act on (N25).

export const OFFLINE =
  "Could not reach TalentSight. Check your internet connection, or that the app is running, and try again.";

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  // Files (FormData) are sent as they are: the browser sets their Content-Type itself.
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await send(`/api${path}`, { ...options, headers });

  if (response.status === 401 && token) {
    sendToLogin();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    // The status travels with the error, so callers can tell "refused" (4xx) from "try again" (5xx, network).
    throw Object.assign(new Error(errorMessage(body.detail, response.status)), { status: response.status });
  }
  if (response.status === 204) {
    return undefined as T; // "No Content": nothing to read
  }
  return response.json() as Promise<T>;
}

// Builds "/path?a=1&b=two" and leaves out anything empty, so the filter bars can pass
// everything they have without checking each value first.
export function withQuery(path: string, values: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

// Live speech to text (Module 8) uses WebSockets. They go to the same server as the page,
// with ws:// instead of http:// (or wss:// instead of https://).
export function socketUrl(path: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api${path}`;
}

// For files (like a CV or the PDF report): same login token, but the answer is a file, not JSON.
export async function apiBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await send(`/api${path}`, { headers });

  if (response.status === 401 && token) {
    sendToLogin();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Object.assign(new Error(errorMessage(body.detail, response.status)), { status: response.status });
  }
  return response.blob();
}

// fetch itself throws when the server cannot be reached at all ("Failed to fetch").
async function send(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw Object.assign(new Error(OFFLINE), { status: 0 });
  }
}

// The saved login has expired: forget it, log in again, and come back to this page afterwards.
function sendToLogin() {
  clearToken();
  const here = window.location.pathname + window.location.search;
  window.location.href = here.startsWith("/login") ? "/login" : `/login?next=${encodeURIComponent(here)}`;
}

// FastAPI sends {"detail": "a sentence"}, or for form errors {"detail": [{"msg": "..."}, ...]}.
// When there is no sentence (a proxy error page, a crash), the status decides what to say.
function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail) {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((problem: { msg: string }) => problem.msg.replace("Value error, ", "")).join(" ");
  }
  if (status === 404) return "That item could not be found. It may have been deleted.";
  if (status === 413) return "The upload is too large. Each CV can be up to 5 MB; try fewer files at once.";
  if (status === 429) return "Too many requests in a short time. Wait a moment and try again.";
  if (status === 502 || status === 503 || status === 504) {
    return "TalentSight is starting up or busy. Wait a few seconds and try again.";
  }
  if (status >= 500) return "Something went wrong on the server. Try again; if it keeps happening, tell your administrator.";
  return "That did not work. Check what you entered and try again.";
}