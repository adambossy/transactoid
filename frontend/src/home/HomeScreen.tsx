import { HomeHeader } from "./HomeHeader";
import { Hero } from "./Hero";
import { StatStrip } from "./StatStrip";
import { FeatureSection } from "./FeatureSection";
import { ClosingCta } from "./ClosingCta";
import { HomeFooter } from "./HomeFooter";
import { home } from "./copy";
import { demos } from "./demos";

/** The public logged-out landing page (meetpenny.app). Pure marketing chrome —
 *  no auth, no API calls; every CTA routes to /sign-up (see home.spec.ts). */
export function HomeScreen() {
  return (
    <div className="marketing relative h-full overflow-y-auto bg-paper font-ui text-ink">
      <div className="grain pointer-events-none fixed inset-0 z-0" />
      <HomeHeader />
      <main className="relative z-10">
        <Hero />
        <StatStrip />
        {home.features.map((f, i) => (
          <FeatureSection key={f.id} {...f} flip={i % 2 === 1} demo={demos[f.id]} />
        ))}
        <ClosingCta />
      </main>
      <HomeFooter />
    </div>
  );
}
