import { ButtonLink, Logo } from "@penny/ui";
import { home } from "./copy";

/** Orange closing band: emblem, serif headline, sign-up CTA. */
export function ClosingCta() {
  return (
    <section className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
      <div className="relative overflow-hidden rounded-[2.5rem] bg-orange px-8 py-16 text-center sm:px-16 sm:py-20">
        <div className="absolute -right-10 -top-10 h-44 w-44 rounded-full bg-navy/15" />
        <div className="absolute -bottom-12 -left-8 h-52 w-52 rounded-full bg-navy/10" />
        <div className="relative">
          <Logo variant="emblem" size={96} className="mx-auto mb-7" />
          <h2 className="font-serif text-5xl font-normal text-ink sm:text-6xl">
            {home.closing.title}
          </h2>
          <p className="mx-auto mt-4 max-w-xl font-ui text-lg text-navy">{home.closing.body}</p>
          <ButtonLink href="/sign-up" size="2xl" className="mt-8">
            {home.closing.cta} →
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
