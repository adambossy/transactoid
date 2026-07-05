import type { ButtonHTMLAttributes, Ref } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** React 19 ref-as-prop; forwarded to the underlying <button>. */
  ref?: Ref<HTMLButtonElement>;
};

/** A round, icon-only button in the cream palette: ink glyph on a transparent
 *  ground with a cream-soft hover and a navy focus ring. Icon-only, so every
 *  use MUST supply an `aria-label`. Pass the glyph (e.g. a lucide icon) as
 *  children — the library stays icon-set agnostic. */
export function IconButton({ className = "", type, ref, ...rest }: Props) {
  const base =
    "inline-flex h-9 w-9 items-center justify-center rounded-full text-ink transition-colors cursor-pointer hover:bg-cream-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <button ref={ref} type={type ?? "button"} className={`${base} ${className}`} {...rest} />
  );
}
