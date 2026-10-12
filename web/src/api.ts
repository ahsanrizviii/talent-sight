import { clearToken, getToken } from "./auth";

// The one function every page uses to call the API.
// It adds "/api" in front, sends the login token, sends and reads JSON,
// and turns errors into readable messages.

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

  const response = await fetch(`/api${path}`, { ...options, headers });

  if (response.status === 401 && token) {
    // The saved token has expired or is no longer valid: forget it and log in again.
    clearToken();
    window.location.href = "/login";
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

// For files (like a CV): same login token, but the answer is a file, not JSON.
export async function apiBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`/api${path}`, { headers });

  if (response.status === 401 && token) {
    clearToken();
    window.location.href = "/login";
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(errorMessage(body.detail, response.status));
  }
  return response.blob();
}

// FastAPI sends {"detail": "a sentence"}, or for form errors {"detail": [{"msg": "..."}, ...]}.
function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((problem: { msg: string }) => problem.msg.replace("Value error, ", "")).join(" ");
  }
  return `Request failed (${status}).`;
}