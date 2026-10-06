export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(`/api${path}`, { ...options, headers });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    
    const message = typeof body.detail === "string" ? body.detail : "Please check the form and try again.";
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T; 
  }

  return response.json() as Promise<T>;
}