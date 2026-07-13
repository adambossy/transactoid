import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "filled" | "outlined";
export type ButtonSize = "md" | "lg" | "xl";

// One padding home per size — callers must not append their own px-*/py-*
// (two padding sets on one element resolve by stylesheet emission order, not
// class order, so an override only wins by luck).
const PADDING: Record<ButtonSize, string> = {
  md: "px-5 py-2",
  lg: "px-7 py-3.5",
  xl: "px-9 py-4",
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
      : "border border-ink text-ink hover:bg-cream-soft";
  return `${base} ${styles} ${className}`;
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export function Button({ variant = "filled", size = "md", className = "", ...rest }: Props) {
  return <button className={buttonClasses(variant, className, size)} {...rest} />;
}
