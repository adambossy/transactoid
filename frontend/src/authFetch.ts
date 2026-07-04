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

/** `fetch` with a JSON content type and a bearer token when one is available. */
export async function authedFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await currentGetter();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(url, { ...init, headers });
}
