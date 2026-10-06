import { clearToken, getToken } from "./auth";

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

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

    const message =
      typeof body.detail === "string"
        ? body.detail
        : "Please check the form and try again.";
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T; 
  }

  return response.json() as Promise<T>;
}