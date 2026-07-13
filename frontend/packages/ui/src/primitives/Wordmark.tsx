import { Logo } from "../logo/Logo";

export interface WordmarkProps {
  /** Logo square size in px; the wordmark text steps down below 40. */
  size?: number;
  /** Sets the wordmark text color (e.g. "text-navy", "text-cream"). */
  className?: string;
}

/** The brand lockup: flat Logo beside the tracked serif "PENNY" wordmark.
 *  Single home for the pairing so header, footer, and auth chrome can't
 *  drift apart. */
export function Wordmark({ size = 40, className = "" }: WordmarkProps) {
  return (
    <span className={`flex items-center gap-3 ${className}`}>
      <Logo variant="flat" size={size} />
      <span
        className={`font-serif font-semibold tracking-[0.22em] ${size < 40 ? "text-xl" : "text-2xl"}`}
      >
        PENNY
      </span>
    </span>
  );
}
