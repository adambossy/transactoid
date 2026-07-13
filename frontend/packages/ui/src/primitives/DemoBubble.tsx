import type { ReactNode } from "react";

export interface DemoBubbleProps {
  /** "user" = right-aligned gold bubble; "penny" = left-aligned cream bubble. */
  role: "user" | "penny";
  children: ReactNode;
}

/** Static chat bubble for marketing/demo conversation previews — NOT the live
 *  chat surface (that's agent-ui). Penny bubbles style any nested <table> to
 *  the template's bordered data-table look. */
export function DemoBubble({ role, children }: DemoBubbleProps) {
  const shape =
    role === "user"
      ? "ml-auto max-w-[80%] rounded-2xl rounded-tr-sm bg-orange text-ink"
      : "mr-auto max-w-[96%] rounded-2xl rounded-tl-sm border border-cream bg-cream-soft text-ink";
  const tables =
    "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs " +
    "[&_th]:border [&_th]:border-ink/15 [&_th]:bg-navy/10 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold " +
    "[&_td]:border [&_td]:border-ink/15 [&_td]:px-2 [&_td]:py-1 " +
    "[&_td:not(:first-child)]:text-right [&_th:not(:first-child)]:text-right";
  return (
    <div className={`px-3.5 py-2.5 font-ui text-sm leading-relaxed ${shape} ${tables}`}>
      {children}
    </div>
  );
}
