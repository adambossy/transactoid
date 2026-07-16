import { NavLink, Wordmark } from "@penny/ui";
import { home } from "./copy";

/** Navy footer band: mark + wordmark, tagline, anchor links. */
export function HomeFooter() {
  return (
    <footer className="bg-navy">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-6 px-5 py-10 sm:flex-row sm:px-8">
        <Wordmark size={40} className="text-cream" />
        <p className="font-ui text-sm text-cream-soft/70">{home.footer.tagline}</p>
        <nav className="flex gap-6 text-cream-soft">
          {home.footer.links.map((n) => (
            <NavLink key={n.href} href={n.href} className="text-xs uppercase tracking-[0.22em]">
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </footer>
  );
}
