import type { ReactNode } from "react";
import { Logo } from "../logo/Logo";

export interface HeaderProps {
  /** Nav content (links, menu). Supplied by the app — the library owns no routing. */
  nav?: ReactNode;
  /** Right-aligned actions (e.g. a CTA button). */
  actions?: ReactNode;
}

/** Logo + PENNY wordmark (left), nav slot (center), actions slot (right),
 *  thin bottom border. Nav content and routing come from the app. */
export function Header({ nav, actions }: HeaderProps) {
  return (
    <header className="flex items-center justify-between gap-6 border-b border-cream px-6 py-4">
      <div className="flex items-center gap-3">
        <Logo variant="emblem" size={40} />
        <span className="font-serif text-2xl font-semibold tracking-wide text-ink">PENNY</span>
      </div>
      {nav ? <nav className="flex items-center gap-6 font-ui text-sm text-ink">{nav}</nav> : null}
      <div className="flex items-center gap-3">{actions}</div>
    </header>
  );
}
