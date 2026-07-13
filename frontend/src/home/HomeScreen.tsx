import { HomeHeader } from "./HomeHeader";
import { Hero } from "./Hero";
import { HomeFooter } from "./HomeFooter";

/** The public logged-out landing page (meetpenny.app). Pure marketing chrome —
 *  no auth, no API calls; every CTA routes to /sign-up (see home.spec.ts). */
export function HomeScreen() {
  return (
    <div className="relative h-full overflow-y-auto bg-paper text-ink">
      <div className="grain pointer-events-none fixed inset-0 z-0" />
      <HomeHeader />
      <main className="relative z-10">
        <Hero />
      </main>
      <HomeFooter />
    </div>
  );
}
