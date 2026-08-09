export const API_BASE = process.env.NEXT_PUBLIC_ADMIN_API_BASE ?? "http://localhost:8000";
const SESSION_STORAGE_KEY = "neuroad.admin.session-token";

let sessionToken: string | null = null;

export type AdminUser = { id: string; email: string; role: string };

export class AdminRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export function restoreAdminSession() {
  if (typeof window !== "undefined") sessionToken = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
}

export async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  const response = await fetch(`${API_BASE}/internal/admin/v1${path}`, { ...init, credentials: "include", headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new AdminRequestError(payload.detail ?? "Internal dashboard request failed.", response.status);
  }
  return response.json() as Promise<T>;
}
