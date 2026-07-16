import type { AnchorHTMLAttributes } from "react";
import { buttonClasses, type ButtonSize, type ButtonVariant } from "./Button";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/** Button-styled <a> for pill CTAs that navigate (e.g. "Meet Penny" → /sign-up). */
export function ButtonLink({ variant = "filled", size = "md", className = "", ...rest }: Props) {
  return (
    <a
      className={`inline-block no-underline ${buttonClasses(variant, className, size)}`}
      {...rest}
    />
  );
}
