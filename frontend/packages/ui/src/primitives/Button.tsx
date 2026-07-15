import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "filled" | "outlined";
export type ButtonSize = "md" | "lg" | "xl" | "2xl";

// One padding home per size — callers must not append their own px-*/py-*
// (two padding sets on one element resolve by stylesheet emission order, not
// class order, so an override only wins by luck). The ladder mirrors the
// design reference: header pill / hero Ask Penny / section CTA / closing CTA.
const PADDING: Record<ButtonSize, string> = {
  md: "px-5 py-2",
  lg: "px-6 py-3",
  xl: "px-7 py-3.5",
  "2xl": "px-9 py-4",
};

/** Shared pill styling for Button and ButtonLink. */
export function buttonClasses(
  variant: ButtonVariant,
  className = "",
  size: ButtonSize = "md",
): string {
  const base = `rounded-full ${PADDING[size]} font-ui text-sm transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`;
  const styles =
    variant === "filled"
      ? "bg-navy text-cream hover:bg-navy-700"
      : "border-[1.5px] border-navy text-navy hover:bg-navy hover:text-cream";
  return `${base} ${styles} ${className}`;
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function Button({ variant = "filled", size = "md", className = "", ...rest }: Props) {
  return <button className={buttonClasses(variant, className, size)} {...rest} />;
}
