/**
 * Shared authed fetch for inline tool cards.
 *
 * Tool renderers (registered by tool name) receive only the tool `part`, not the
 * Clerk `getToken` the screens thread as a prop — so the card path needs a
 * module-level token source. `setAuthTokenGetter` is wired once from the signed-in
 * screen; in dev-principal mode no getter is set and requests carry no bearer
 * (the backend uses the env-pinned principal), which is exactly what the e2e
 * harness relies on.
 */

type TokenGetter = () => Promise<string | null>;

let currentGetter: TokenGetter = async () => null;

/** Point the shared fetch at the app's token source (Clerk's getToken). */
export function setAuthTokenGetter(getter: TokenGetter): void {
  currentGetter = getter;
}

/**
 * Bearer `Authorization` header from an injected token source, or `{}` when no
 * token is available (dev-principal mode). Screens thread their prop `getToken`
 * here; the module-level `authedFetch` uses the once-wired getter.
 */
export async function authHeaders(
  getToken: TokenGetter,
): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** `fetch` with a JSON content type and a bearer token when one is available. */
export async function authedFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
    ...(await authHeaders(currentGetter)),
  };
  return fetch(url, { ...init, headers });
}
