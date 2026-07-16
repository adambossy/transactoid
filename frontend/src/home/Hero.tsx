import { useState } from "react";
import { useNavigate } from "react-router";
import { AccentUnderline, Chip, EyebrowPill, Input, Logo } from "@penny/ui";
import { home } from "./copy";

/** Hero: headline + placeholder question input + suggestion chips (left),
 *  emblem on a cream oval with accent dots (right). Every affordance routes
 *  to sign-up — the landing page never talks to the agent. */
export function Hero() {
  const [question, setQuestion] = useState("");
  const navigate = useNavigate();
  const goSignUp = () => navigate("/sign-up");

  return (
    <section className="mx-auto max-w-7xl px-5 pt-14 pb-16 sm:px-8 sm:pt-20">
      <div className="grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="animate-rise-in motion-reduce:animate-none">
          <EyebrowPill className="mb-6">{home.eyebrow}</EyebrowPill>
          <h1 className="font-serif text-6xl font-normal leading-[1.02] text-navy sm:text-7xl">
            {home.hero.title1}
            <br />
            {home.hero.title2Pre}
            <AccentUnderline>{home.hero.titleAccent}</AccentUnderline>
          </h1>
          <p className="mt-6 max-w-lg font-ui text-lg text-ink">{home.hero.body}</p>
          <div className="mt-8 max-w-xl">
            <Input
              value={question}
              onChange={setQuestion}
              onSubmit={goSignUp}
              placeholder={home.hero.inputPlaceholder}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {home.hero.chips.map((c) => (
              <Chip key={c.label} emoji={c.emoji} label={c.label} onClick={goSignUp} />
            ))}
          </div>
        </div>
        <div className="relative mx-auto flex aspect-[4/3] w-full max-w-lg items-center justify-center">
          <div className="absolute inset-0 rounded-full bg-cream" />
          <div className="absolute right-3 top-3 h-16 w-16 rounded-full bg-orange/90" />
          <div className="absolute bottom-5 left-6 h-7 w-7 rounded-full bg-navy" />
          <Logo
            variant="emblem"
            size={256}
            className="relative transition-transform duration-500 hover:-translate-y-1.5 hover:-rotate-1"
          />
        </div>
      </div>
    </section>
  );
}
