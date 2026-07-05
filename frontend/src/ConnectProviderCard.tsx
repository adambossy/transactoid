import { useState } from "react";
import { Button, Card } from "@penny/ui";
import { authHeaders } from "./authFetch";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

interface ProviderOption {
  id: string;
  label: string;
  kind: string;
}

/** Structured output of the `connect_provider` agent tool. */
export interface ConnectProviderData {
  type: "connect_provider";
  providers: ProviderOption[];
  settings_url: string;
}

/**
 * Inline "Connect a provider" card rendered in chat for the `connect_provider`
 * tool output. Lets the user paste an API key without leaving the conversation;
 * the key is POSTed to the vault and never rendered back. Once connected, the
 * next turn unblocks. Registration with the phase-5 tool-renderer is a follow-up
 * (see phase-2b-decisions D8); this component is ready to drop in.
 */
export function ConnectProviderCard({
  data,
  getToken,
  onConnected,
}: {
  data: ConnectProviderData;
  getToken: GetToken;
  onConnected?: () => void;
}) {
  const [provider, setProvider] = useState(data.providers[0]?.id ?? "google");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      setKey("");
      setDone(true);
      onConnected?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <Card data-testid="connect-provider-done">
        <p className="text-sm text-ink">
          Connected. Send your message again to continue.
        </p>
      </Card>
    );
  }

  return (
    <Card data-testid="connect-provider-card">
      <h3 className="font-ui text-sm font-medium text-ink">Connect a provider</h3>
      <p className="mt-1 text-sm text-steel">
        Use your own AI provider key to keep going. Stored encrypted, never shown
        again.
      </p>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          className="rounded-full border border-cream bg-paper px-4 py-2 font-ui text-sm text-ink"
          data-testid="connect-provider-select"
        >
          {data.providers.map((p) => (
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
          data-testid="connect-provider-input"
          className="min-w-0 flex-1 rounded-full border border-cream bg-paper px-4 py-2 font-ui text-sm text-ink placeholder:text-steel focus:outline-none"
        />
        <Button
          variant="filled"
          disabled={busy || !key.trim()}
          onClick={() => void connect()}
          data-testid="connect-provider-submit"
        >
          Connect
        </Button>
      </div>
      <a
        href={data.settings_url}
        className="mt-3 inline-block text-xs text-steel underline"
      >
        Manage in settings
      </a>
    </Card>
  );
}
