import { Logo, NavLink } from "@penny/ui";
import { home } from "./copy";

/** Navy footer band: mark + wordmark, tagline, anchor links. */
export function HomeFooter() {
  return (
    <footer className="bg-navy">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-6 px-5 py-10 sm:flex-row sm:px-8">
        <div className="flex items-center gap-3">
          <Logo variant="flat" size={40} />
          <span className="font-serif text-2xl font-semibold tracking-[0.22em] text-cream">
            PENNY
          </span>
        </div>
        <p className="font-ui text-sm text-cream-soft/70">{home.footer.tagline}</p>
        <nav className="flex gap-6 text-cream-soft">
          {home.nav.slice(0, 3).map((n) => (
            <NavLink key={n.href} href={n.href} className="text-xs uppercase tracking-[0.22em]">
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </footer>
  );
}
