import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "filled" | "outlined";

/** Shared pill styling for Button and ButtonLink. */
export function buttonClasses(variant: ButtonVariant, className = ""): string {
  const base =
    "rounded-full px-5 py-2 font-ui text-sm transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "filled"
      ? "bg-navy text-cream hover:bg-navy-700"
      : "border border-ink text-ink hover:bg-cream-soft";
  return `${base} ${styles} ${className}`;
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant };

export function Button({ variant = "filled", className = "", ...rest }: Props) {
  return <button className={buttonClasses(variant, className)} {...rest} />;
}
