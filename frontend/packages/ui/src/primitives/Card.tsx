import type { HTMLAttributes } from "react";

/** Bordered rounded surface (the chat/product panel). Forwards native div props. */
export function Card({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-2xl border border-cream bg-cream-soft p-5 ${className}`}
      {...rest}
    />
  );
}
