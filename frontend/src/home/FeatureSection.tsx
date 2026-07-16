import type { ReactNode } from "react";
import { AccentUnderline, ButtonLink } from "@penny/ui";

export interface FeatureSectionProps {
  id: string;
  eyebrow: string;
  title: string;
  /** Trailing headline fragment rendered with the gold underline. */
  titleAccent?: string;
  body: string;
  cta: string;
  /** Demo conversation (DemoBubbles) shown in the ringed panel. */
  demo: ReactNode;
  /** Alternate row: cream band, demo panel first at lg. */
  flip?: boolean;
}

/** One feature row: eyebrow + serif headline + body + sign-up CTA on one side,
 *  a ringed demo-conversation panel on the other; `flip` alternates sides and
 *  paints the cream band (template sections 02/04/06). */
export function FeatureSection({
  id,
  eyebrow,
  title,
  titleAccent,
  body,
  cta,
  demo,
  flip = false,
}: FeatureSectionProps) {
  return (
    <section id={id} className={flip ? "bg-cream-soft py-20" : "py-20"}>
      <div className="mx-auto grid max-w-7xl items-center gap-12 px-5 sm:px-8 lg:grid-cols-2">
        <div className={flip ? "order-1 lg:order-2" : ""}>
          <span className="font-ui text-xs uppercase tracking-[0.22em] text-orange">
            {eyebrow}
          </span>
          <h2 className="mt-3 font-serif text-5xl font-normal text-navy">
            {title}
            {titleAccent ? <> <AccentUnderline>{titleAccent}</AccentUnderline></> : null}
          </h2>
          <p className="mt-4 max-w-md font-ui text-lg text-ink">{body}</p>
          <ButtonLink href="/sign-up" size="xl" className="mt-7">
            {cta} →
          </ButtonLink>
        </div>
        <div
          className={`rounded-[1.8rem] bg-paper p-6 ring-2 ring-navy ${flip ? "order-2 lg:order-1" : ""}`}
        >
          <div className="flex flex-col gap-3">{demo}</div>
        </div>
      </div>
    </section>
  );
}
