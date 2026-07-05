import type { ReactNode } from "react";

export interface AppShellProps {
  header?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}

/** The cream-paper page frame: sets the page background, text color, and UI font,
 *  and stacks header above a centered max-width content column above footer. */
export function AppShell({ header, footer, children }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-paper font-ui text-ink">
      {header}
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">{children}</main>
      {footer}
    </div>
  );
}
