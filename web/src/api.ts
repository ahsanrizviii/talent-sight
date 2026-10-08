import { clearToken, getToken } from "./auth";

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`/api${path}`, { ...options, headers });

  if (response.status === 401 && token) {

    clearToken();
    window.location.href = "/login";
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(errorMessage(body.detail, response.status));
  }

  if (response.status === 204) {
    return undefined as T; 
  }

  return response.json() as Promise<T>;
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") {
    return detail;
  }
  
  if (Array.isArray(detail)) {
    return detail
            .map((problem: { msg: string }) => problem.msg.replace("Value error, ", ""))
      .join(" ");
  }
  
  return `Request failed (${status}).`;
}