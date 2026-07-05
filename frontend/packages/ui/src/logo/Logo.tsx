import emblem from "../assets/logo-emblem.png";
import flat from "../assets/logo-flat.png";

export type LogoVariant = "emblem" | "flat";

export interface LogoProps {
  /** "emblem" = primary full-color mark; "flat" = single-tone mark for small
   *  or single-color contexts. */
  variant?: LogoVariant;
  /** Rendered square size in px. */
  size?: number;
  className?: string;
}

const SOURCES: Record<LogoVariant, string> = { emblem, flat };

export function Logo({ variant = "emblem", size = 40, className = "" }: LogoProps) {
  return (
    <img
      src={SOURCES[variant]}
      alt="Penny"
      width={size}
      height={size}
      className={className}
      style={{ objectFit: "contain" }}
    />
  );
}
