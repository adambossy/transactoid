import type { ReactNode } from "react";
import { Logo } from "../logo/Logo";

export interface FooterProps {
  children?: ReactNode;
}

/** Flat-logo mark + children. */
export function Footer({ children }: FooterProps) {
  return (
    <footer className="flex items-center gap-3 border-t border-cream px-6 py-5 font-ui text-sm text-steel">
      <Logo variant="flat" size={28} />
      {children}
    </footer>
  );
}
