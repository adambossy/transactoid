import type { ReactNode } from "react";

/** Inline gold underline swash under serif display text (the template's
 *  `.underline-classic`). Wrap only the emphasized fragment of a headline. */
export function AccentUnderline({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`relative inline-block ${className}`}>
      {children}
      <span
        aria-hidden="true"
        className="absolute bottom-[-0.08em] left-0 h-[3px] w-full bg-orange"
      />
    </span>
  );
}
