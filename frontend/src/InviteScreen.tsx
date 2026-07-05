import { useCallback, useEffect, useState } from "react";
import { AppShell, Button, Card } from "@penny/ui";
import { authHeaders } from "./authFetch";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

const ACTIVE_ACCOUNT_MESSAGE =
  "That email already has a Penny account. To join this household they'll need " +
  "to sign up with a new account.";

/**
 * Invite screen: a household member invites a NEW email into their household.
 * Lists pending (un-claimed) invites, each with a revoke control. Inviting an
 * email that already has an active account surfaces the 409 "start fresh"
 * message rather than a generic error — the invite is for accountless users
 * only.
 */
export function InviteScreen({ getToken }: { getToken: GetToken }) {
  const [pending, setPending] = useState<string[]>([]);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/invites", { headers: await authHeaders(getToken) });
      if (!res.ok) throw new Error(`Failed to load invites (${res.status})`);
      setPending((await res.json()).invites ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function invite() {
    const value = email.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/invites", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
        body: JSON.stringify({ email: value }),
      });
      if (res.status === 409) {
        setError(ACTIVE_ACCOUNT_MESSAGE);
        return;
      }
      if (!res.ok) throw new Error(`Failed to send invite (${res.status})`);
      setEmail("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(target: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/invites/${encodeURIComponent(target)}`, {
        method: "DELETE",
        headers: await authHeaders(getToken),
      });
      if (!res.ok) throw new Error(`Failed to revoke (${res.status})`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        <h1 className="font-display text-3xl text-ink">Invite to your household</h1>
        <p className="text-sm text-steel">
          Invite someone new to Penny — they&apos;ll sign up straight into your
          household. Already have a Penny account? They&apos;ll need to start fresh.
        </p>

        {error && (
          <Card className="border-red-300 bg-red-50" data-testid="invite-error">
            <p className="text-sm text-red-700">{error}</p>
          </Card>
        )}

        <Card data-testid="invite-card">
          <h2 className="font-ui text-sm uppercase tracking-wide text-steel">
            Send an invitation
          </h2>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void invite();
              }}
              placeholder="name@example.com"
              autoComplete="off"
              data-testid="invite-email-input"
              className="min-w-0 flex-1 rounded-full border border-cream bg-paper px-4 py-2 font-ui text-sm text-ink placeholder:text-steel focus:outline-none"
            />
            <Button
              variant="filled"
              disabled={busy || !email.trim()}
              onClick={() => void invite()}
              data-testid="send-invite"
            >
              Send invite
            </Button>
          </div>
        </Card>

        <Card data-testid="pending-card">
          <h2 className="font-ui text-sm uppercase tracking-wide text-steel">
            Pending invites
          </h2>
          {loading ? (
            <p className="mt-2 text-sm text-steel">Loading…</p>
          ) : pending.length === 0 ? (
            <p className="mt-2 text-sm text-steel" data-testid="no-pending">
              No pending invites.
            </p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {pending.map((p) => (
                <li
                  key={p}
                  className="flex items-center justify-between rounded-xl border border-cream bg-paper px-4 py-3"
                  data-testid="pending-invite"
                >
                  <span className="font-ui text-sm text-ink">{p}</span>
                  <Button
                    variant="outlined"
                    disabled={busy}
                    onClick={() => void revoke(p)}
                    data-testid={`revoke-${p}`}
                  >
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
