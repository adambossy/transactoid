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
      ? "ml-auto max-w-[80%] rounded-2xl rounded-tr-[0.3rem] bg-orange text-ink"
      : "mr-auto max-w-[96%] rounded-2xl rounded-tl-[0.3rem] border border-ink/8 bg-cream-soft text-ink";
  const tables =
    "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-[0.76rem] " +
    "[&_th]:border [&_th]:border-ink/16 [&_th]:bg-navy/8 [&_th]:px-[0.45rem] [&_th]:py-1 [&_th]:text-left [&_th]:font-bold " +
    "[&_td]:border [&_td]:border-ink/16 [&_td]:px-[0.45rem] [&_td]:py-1 " +
    "[&_td:not(:first-child)]:text-right [&_th:not(:first-child)]:text-right";
  return (
    <div
      className={`px-[0.85rem] py-[0.6rem] font-ui text-[0.83rem] leading-[1.45] ${shape} ${tables}`}
    >
      {children}
    </div>
  );
}
