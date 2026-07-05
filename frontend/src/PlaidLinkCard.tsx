import { useEffect, useState } from "react";
import { usePlaidLink } from "react-plaid-link";
import { Button, Card } from "@penny/ui";
import { authedFetch } from "./authFetch";

/** Structured output of the `connect_bank_account` agent tool. */
type Output = { mode?: string; link_token?: string };

/** The tool-renderer part (agent-ui passes only `{ state, output }`). */
type ToolPart = { state?: string; output?: unknown };

// The conversation id the chat POST uses as its `id` (localStorage-backed), so
// the exchange resumes the same conversation. Mirrors ChatScreen's SESSION_KEY.
const SESSION_KEY = "penny:sessionId";

function conversationId(): string {
  return localStorage.getItem(SESSION_KEY) ?? "default";
}

/**
 * Inline Plaid Link card rendered as generative UI for the `connect_bank_account`
 * tool output. Hosts `react-plaid-link`; on success it POSTs the `public_token`
 * to the server-side exchange (never exchanging client-side). OAuth-redirect
 * institutions resume via `receivedRedirectUri` when the conversation rehydrates.
 */
export function PlaidLinkCard({ part }: { part: ToolPart }) {
  const output = part.output as Output | undefined;
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `fetch` only rejects on a network error, so a 4xx/5xx would otherwise flip
  // the card to "Bank linked" falsely — gate success on `res.ok` and surface a
  // failure state instead (mirrors ConnectProviderCard's try/catch + error card).
  async function exchange(publicToken: string): Promise<void> {
    setError(null);
    try {
      const res = await authedFetch("/api/plaid/exchange", {
        method: "POST",
        body: JSON.stringify({
          public_token: publicToken,
          conversation_id: conversationId(),
        }),
      });
      if (!res.ok) throw new Error(`Failed to link bank (${res.status})`);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const { open, ready } = usePlaidLink({
    token: output?.link_token ?? null,
    receivedRedirectUri: location.href.includes("oauth_state_id")
      ? location.href
      : undefined,
    onSuccess: (publicToken) => {
      void exchange(publicToken);
    },
  });

  // E2E hook: drive the success path without the hosted Plaid popup (which can't
  // be automated headlessly — the real sandbox link-through is a manual step).
  // Dev-only (like main.tsx's `/ui` gallery), so the fake-token hook against the
  // real endpoint never ships in a production build.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const w = window as unknown as {
      __pennyPlaidExchange?: (pt?: string) => void;
    };
    w.__pennyPlaidExchange = (pt = "public-e2e") => void exchange(pt);
    return () => {
      delete w.__pennyPlaidExchange;
    };
  }, []);

  if (part.state !== "output-available" || output?.mode !== "hosted") return null;
  if (done) {
    return (
      <Card data-testid="plaid-card">
        <p className="text-sm text-ink">Bank linked — syncing has started.</p>
      </Card>
    );
  }
  return (
    <Card data-testid="plaid-card" data-tool="connect_bank_account">
      <h3 className="font-ui text-sm font-medium text-ink">Connect a bank</h3>
      <p className="mt-1 text-sm text-steel">
        Securely connect a bank account via Plaid, without leaving the chat.
      </p>
      {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      <div className="mt-3">
        <Button
          variant="filled"
          disabled={!ready}
          onClick={() => open()}
          data-testid="plaid-connect"
        >
          Connect a bank
        </Button>
      </div>
    </Card>
  );
}
