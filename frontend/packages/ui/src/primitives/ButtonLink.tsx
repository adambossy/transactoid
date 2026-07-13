import type { AnchorHTMLAttributes } from "react";
import { buttonClasses, type ButtonVariant } from "./Button";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant };

/** Button-styled <a> for pill CTAs that navigate (e.g. "Meet Penny" → /sign-up). */
export function ButtonLink({ variant = "filled", className = "", ...rest }: Props) {
  return <a className={`inline-block no-underline ${buttonClasses(variant, className)}`} {...rest} />;
}
