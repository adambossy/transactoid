import type { ReactNode } from "react";

export interface EyebrowPillProps {
  children: ReactNode;
  className?: string;
}

/** Small teal-filled, letter-spaced uppercase pill (e.g. "YOUR FINANCE SAVANT"). */
export function EyebrowPill({ children, className = "" }: EyebrowPillProps) {
  return (
    <span
      className={`inline-block rounded-full bg-navy px-3 py-1 font-ui text-xs font-medium uppercase tracking-[0.18em] text-cream ${className}`}
    >
      {children}
    </span>
  );
}
