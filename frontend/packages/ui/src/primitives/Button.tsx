import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "filled" | "outlined";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant };

export function Button({ variant = "filled", className = "", ...rest }: Props) {
  const base =
    "rounded-full px-5 py-2 font-ui text-sm transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "filled"
      ? "bg-navy text-cream hover:bg-navy-700"
      : "border border-ink text-ink hover:bg-cream-soft";
  return <button className={`${base} ${styles} ${className}`} {...rest} />;
}
