export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public retryable = false,
    public status = 0,
  ) {
    super(message);
  }
}
let csrf = "";
export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      method,
      credentials: "include",
      headers: {
        ...(body && !(body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(method !== "GET" && csrf ? { "X-CSRF-Token": csrf } : {}),
      },
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "NETWORK_ERROR",
      "Could not reach the service. Your entered details are preserved.",
      true,
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      data?.error?.code ?? String(response.status),
      response.status === 401
        ? "Your workspace session has expired. Create a new workspace to continue. Previous cases may be inaccessible."
        : (data?.error?.message ??
            "The service could not complete this request."),
      data?.error?.retryable ?? false,
      response.status,
    );
  return data as T;
}
export interface GuestSession {
  workspace_id: string;
  expires_at: string;
  csrf_token: string;
}
export async function openWorkspace(fresh = false) {
  let session: GuestSession;
  if (fresh) session = await request<GuestSession>("/guest-session", "POST");
  else {
    try {
      session = await request<GuestSession>("/session");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401)
        session = await request<GuestSession>("/guest-session", "POST");
      else throw e;
    }
  }
  if (!session.workspace_id || !session.csrf_token || !session.expires_at)
    throw new ApiError(
      "SESSION_CONTRACT",
      "The session service returned incomplete workspace metadata.",
    );
  csrf = session.csrf_token;
  return session;
}
