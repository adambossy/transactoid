import { useState } from "react";
import { AppShell } from "./shell/AppShell";
import { Header } from "./shell/Header";
import { Footer } from "./shell/Footer";
import { Logo } from "./logo/Logo";
import { Button } from "./primitives/Button";
import { Chip } from "./primitives/Chip";
import { EyebrowPill } from "./primitives/EyebrowPill";
import { Card } from "./primitives/Card";
import { Input } from "./primitives/Input";
import { NavLink } from "./primitives/NavLink";
import { AccentUnderline } from "./primitives/AccentUnderline";
import { ButtonLink } from "./primitives/ButtonLink";
import { DemoBubble } from "./primitives/DemoBubble";
import { Wordmark } from "./primitives/Wordmark";

/** A labeled block wrapping one primitive example, carrying a stable
 *  data-testid for the E2E gallery guard. */
function Sample({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <section data-testid={id} className="mb-8">
      <h2 className="mb-3 font-serif text-lg text-navy">{label}</h2>
      <div className="flex flex-wrap items-center gap-4">{children}</div>
    </section>
  );
}

/** Renders one labeled example of every @penny/ui primitive inside AppShell —
 *  the visual preview and the Playwright E2E target. Presentational only. */
export function Gallery() {
  const [query, setQuery] = useState("");

  const nav = (
    <>
      <span>Analyze</span>
      <span>Project</span>
      <span>Budget</span>
      <span>Forecast</span>
      <span>Trends</span>
    </>
  );

  return (
    <AppShell
      header={
        <div data-testid="ui-header">
          <Header nav={nav} actions={<Button variant="outlined">Meet Penny</Button>} />
        </div>
      }
      footer={
        <div data-testid="ui-footer">
          <Footer>Penny — your finance savant</Footer>
        </div>
      }
    >
      <Sample id="ui-eyebrowpill" label="EyebrowPill">
        <EyebrowPill>Your finance savant</EyebrowPill>
      </Sample>

      <Sample id="ui-logo-emblem" label="Logo — emblem">
        <Logo variant="emblem" size={64} />
      </Sample>

      <Sample id="ui-logo-flat" label="Logo — flat">
        <Logo variant="flat" size={64} />
      </Sample>

      <Sample id="ui-wordmark" label="Wordmark">
        <Wordmark className="text-navy" />
      </Sample>

      <Sample id="ui-button-filled" label="Button — filled">
        <Button variant="filled">Ask Penny</Button>
      </Sample>

      <Sample id="ui-button-outlined" label="Button — outlined">
        <Button variant="outlined">Meet Penny</Button>
      </Sample>

      <Sample id="ui-chip" label="Chip">
        <Chip emoji="📊" label="Analyze my spending" />
      </Sample>

      <Sample id="ui-input" label="Input">
        <div className="w-full max-w-md">
          <Input value={query} onChange={setQuery} placeholder="Ask Penny anything…" />
        </div>
      </Sample>

      <Sample id="ui-navlink" label="NavLink">
        <span className="text-navy">
          <NavLink href="#ui-navlink">Analyze</NavLink>
        </span>
      </Sample>

      <Sample id="ui-accent-underline" label="AccentUnderline">
        <span className="font-serif text-3xl font-semibold text-navy">
          your <AccentUnderline>finance savant.</AccentUnderline>
        </span>
      </Sample>

      <Sample id="ui-buttonlink" label="ButtonLink">
        <ButtonLink variant="filled" href="#ui-buttonlink">
          Ask Penny →
        </ButtonLink>
        <ButtonLink variant="outlined" href="#ui-buttonlink">
          Meet Penny
        </ButtonLink>
      </Sample>

      <Sample id="ui-demobubble" label="DemoBubble">
        <div className="flex w-full max-w-md flex-col gap-3">
          <DemoBubble role="user">Where did my spending surge last year?</DemoBubble>
          <DemoBubble role="penny">
            Three months broke your baseline:
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Spend</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Sep</td>
                  <td>$5,900</td>
                </tr>
                <tr>
                  <td>Dec</td>
                  <td>$7,200</td>
                </tr>
              </tbody>
            </table>
            All <b>one-offs</b>, not a lifestyle shift.
          </DemoBubble>
        </div>
      </Sample>

      <Sample id="ui-card" label="Card">
        <Card>
          <p className="font-ui text-sm text-ink">
            A bordered rounded surface — the chat/product panel.
          </p>
        </Card>
      </Sample>
    </AppShell>
  );
}
