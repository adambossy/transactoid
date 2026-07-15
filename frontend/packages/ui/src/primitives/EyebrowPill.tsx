import type { ReactNode } from "react";

export interface EyebrowPillProps {
  children: ReactNode;
  className?: string;
}

/** Small teal-filled, letter-spaced uppercase pill (e.g. "YOUR FINANCE SAVANT"). */
export function EyebrowPill({ children, className = "" }: EyebrowPillProps) {
  return (
    <span
      className={`inline-block rounded-full bg-navy px-4 py-1.5 font-ui text-xs uppercase tracking-[0.22em] text-cream ${className}`}
    >
      {children}
    </span>
  );
}
