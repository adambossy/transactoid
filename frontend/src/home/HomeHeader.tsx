import { ButtonLink, NavLink, Wordmark } from "@penny/ui";
import { home } from "./copy";

/** Sticky translucent landing header: mark + wordmark, anchor nav (md+),
 *  Sign in / Meet Penny CTAs. Marketing chrome — deliberately not the app's
 *  @penny/ui Header (sticky + blur + wordmark-link are landing-only). */
export function HomeHeader() {
  return (
    <header className="sticky top-0 z-40 border-b-[1.5px] border-navy bg-paper/[0.82] backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-5 py-3 sm:px-8">
        <a href="/" className="no-underline">
          <Wordmark size={44} className="text-navy" />
        </a>
        <nav className="hidden items-center gap-8 text-navy md:flex">
          {home.nav.map((n) => (
            <NavLink key={n.href} href={n.href}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-5 text-navy">
          <NavLink href="/sign-in">{home.header.signIn}</NavLink>
          <ButtonLink variant="outlined" href="/sign-up">
            {home.header.cta}
          </ButtonLink>
        </div>
      </div>
    </header>
  );
}
