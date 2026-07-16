import { home } from "./copy";

/** Four-up serif stat band under the hero. */
export function StatStrip() {
  return (
    <section className="border-y border-ink/15 bg-cream-soft">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-5 py-8 text-center sm:grid-cols-4 sm:px-8">
        {home.stats.map((s) => (
          <div key={s.title}>
            <p className="font-serif text-4xl font-normal text-navy">{s.title}</p>
            <p className="mt-1 font-ui text-xs uppercase tracking-[0.22em] text-navy-700">{s.sub}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
