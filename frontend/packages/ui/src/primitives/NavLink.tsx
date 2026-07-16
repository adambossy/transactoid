import type { AnchorHTMLAttributes } from "react";

/** Text link with the brand hover treatment: a gold underline growing in from
 *  the left. Inherits its text color (`text-current`) so light-on-navy and
 *  ink-on-paper contexts both work; renders a plain <a> — routing stays with
 *  the app. */
export function NavLink({
  className = "",
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a className={`group relative font-ui text-sm text-current no-underline ${className}`} {...rest}>
      {children}
      <span
        aria-hidden="true"
        className="absolute -bottom-1 left-0 h-0.5 w-0 bg-orange transition-all duration-300 group-hover:w-full"
      />
    </a>
  );
}
