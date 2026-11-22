export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Method = "GET" | "POST" | "DELETE";

type RequestOptions = {
  method?: Method;
  body?: unknown;
  auth?: boolean;
  withCookie?: boolean;
};

type ErrorBody = {
  error?: string;
  message?: string;
  detail?: string | { code?: string; message?: string } | unknown[];
};

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSignedOut: (() => void) | null = null;

export function setSignedOutHandler(handler: (() => void) | null): void {
  onSignedOut = handler;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

function codeOf(status: number, body: ErrorBody | null): string {
  if (body?.error) return body.error;
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (detail && !Array.isArray(detail) && typeof detail === "object" && detail.code) return detail.code;
  if (status === 422) return "invalid_input";
  if (status === 429) return "rate_limited";
  return "generic";
}

async function readError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as ErrorBody | null;
  return new ApiError(response.status, codeOf(response.status, body), body?.message ?? response.statusText);
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  try {
    return await fetch(`${API_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: options.withCookie ? "include" : "omit",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network", "network error");
  }
}

async function refreshNow(): Promise<boolean> {
  const response = await send("/auth/refresh", { method: "POST", auth: false, withCookie: true });
  if (!response.ok) {
    accessToken = null;
    return false;
  }
  accessToken = ((await response.json()) as { access_token: string }).access_token;
  return true;
}

async function refreshAcrossTabs(): Promise<boolean> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks) return refreshNow();
  let refreshed = false;
  await locks.request("vapas-refresh", async () => {
    refreshed = await refreshNow();
  });
  return refreshed;
}

export function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing;
  const pending = refreshAcrossTabs().finally(() => {
    refreshing = null;
  });
  refreshing = pending;
  return pending;
}

async function call(path: string, options: RequestOptions): Promise<Response> {
  let response = await send(path, options);
  if (response.status === 401 && options.auth !== false) {
    if (await refreshSession()) {
      response = await send(path, options);
    }
    if (response.status === 401) {
      accessToken = null;
      onSignedOut?.();
    }
  }
  if (!response.ok) throw await readError(response);
  return response;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await call(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiBlob(path: string): Promise<Blob> {
  return (await call(path, {})).blob();
}
