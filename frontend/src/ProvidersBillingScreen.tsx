import { useCallback, useEffect, useState } from "react";
import { AppShell, Button, Card } from "@penny/ui";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

interface MaskedCredential {
  provider: string;
  kind: string;
  hint: string | null;
  updated_at: string | null;
}

interface Billing {
  remaining_cents: number;
  subsidy_granted_cents: number;
  provider: string;
  credentials: MaskedCredential[];
}

const PROVIDERS = [
  { id: "google", label: "Google (Gemini)" },
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
];

async function authHeaders(getToken: GetToken): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function formatDollars(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function ProvidersBillingScreen({ getToken }: { getToken: GetToken }) {
  const [billing, setBilling] = useState<Billing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("google");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/me/billing", {
        headers: await authHeaders(getToken),
      });
      if (!res.ok) throw new Error(`Failed to load billing (${res.status})`);
      setBilling(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function connect() {
    if (!key.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/providers/${provider}/key`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
        body: JSON.stringify({ provider, key: key.trim() }),
      });
      if (!res.ok) throw new Error(`Failed to connect key (${res.status})`);
      setKey(""); // never keep the plaintext around after a successful save
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(p: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/providers/${p}`, {
        method: "DELETE",
        headers: await authHeaders(getToken),
      });
      if (!res.ok) throw new Error(`Failed to disconnect (${res.status})`);
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
        <h1 className="font-display text-3xl text-ink">Providers &amp; billing</h1>

        {error && (
          <Card className="border-red-300 bg-red-50" data-testid="billing-error">
            <p className="text-sm text-red-700">{error}</p>
          </Card>
        )}

        {loading ? (
          <Card>
            <p className="text-sm text-steel">Loading…</p>
          </Card>
        ) : (
          billing && (
            <>
              <Card data-testid="credits-card">
                <h2 className="font-ui text-sm uppercase tracking-wide text-steel">
                  Free credits remaining
                </h2>
                <p className="mt-1 font-display text-4xl text-ink" data-testid="remaining">
                  {formatDollars(billing.remaining_cents)}
                </p>
                <p className="mt-1 text-sm text-steel">
                  of {formatDollars(billing.subsidy_granted_cents)} granted · currently
                  using{" "}
                  <span className="font-medium text-ink">
                    {billing.provider === "subsidy" ? "Penny credits" : billing.provider}
                  </span>
                </p>
              </Card>

              <Card data-testid="connect-card">
                <h2 className="font-ui text-sm uppercase tracking-wide text-steel">
                  Connect your own key
                </h2>
                <p className="mt-1 text-sm text-steel">
                  Your key is stored encrypted and never shown again.
                </p>
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <select
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                    className="rounded-full border border-cream bg-paper px-4 py-2 font-ui text-sm text-ink"
                    data-testid="provider-select"
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="password"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder="sk-…"
                    autoComplete="off"
                    data-testid="api-key-input"
                    className="min-w-0 flex-1 rounded-full border border-cream bg-paper px-4 py-2 font-ui text-sm text-ink placeholder:text-steel focus:outline-none"
                  />
                  <Button
                    variant="filled"
                    disabled={busy || !key.trim()}
                    onClick={() => void connect()}
                    data-testid="connect-key"
                  >
                    Connect
                  </Button>
                </div>
              </Card>

              <Card data-testid="credentials-card">
                <h2 className="font-ui text-sm uppercase tracking-wide text-steel">
                  Connected providers
                </h2>
                {billing.credentials.length === 0 ? (
                  <p className="mt-2 text-sm text-steel" data-testid="no-credentials">
                    None connected — you&apos;re on Penny credits.
                  </p>
                ) : (
                  <ul className="mt-3 flex flex-col gap-2">
                    {billing.credentials.map((c) => (
                      <li
                        key={c.provider}
                        className="flex items-center justify-between rounded-xl border border-cream bg-paper px-4 py-3"
                        data-testid={`credential-${c.provider}`}
                      >
                        <span className="font-ui text-sm text-ink">
                          {c.provider} · <span className="text-steel">{c.hint}</span>
                        </span>
                        <Button
                          variant="outlined"
                          disabled={busy}
                          onClick={() => void disconnect(c.provider)}
                          data-testid={`disconnect-${c.provider}`}
                        >
                          Disconnect
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          )
        )}
      </div>
    </AppShell>
  );
}
