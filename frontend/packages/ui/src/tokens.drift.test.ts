import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { tokens } from "./tokens";

const here = dirname(fileURLToPath(import.meta.url));
const themeCss = readFileSync(join(here, "theme.css"), "utf8");

/**
 * theme.css's `@theme` block is the single source of truth for the palette and
 * font families. tokens.ts re-exports the identical values for JS consumers.
 * This test parses the `@theme` block and asserts tokens.ts cannot drift from it.
 *
 * Mapping between the two homes:
 *   --color-paper        -> paper
 *   --color-cream-soft   -> creamSoft
 *   --font-display       -> fontDisplay
 * i.e. strip the `--color-`/`--font-` prefix, camel-case the remainder, and for
 * fonts prepend `font`.
 */
function camel(kebab: string): string {
  return kebab.replace(/-([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

function parseThemeBlock(css: string): Record<string, string> {
  const match = css.match(/@theme\s*\{([\s\S]*?)\}/);
  if (!match) throw new Error("no @theme block found in theme.css");
  const body = match[1];
  const out: Record<string, string> = {};
  const declRe = /--(color|font)-([a-z0-9-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = declRe.exec(body)) !== null) {
    const [, kind, name, rawValue] = m;
    const value = rawValue.trim();
    const key = kind === "color" ? camel(name) : "font" + camel(`-${name}`);
    out[key] = value;
  }
  return out;
}

describe("token drift guard", () => {
  it("tokens.ts exactly mirrors theme.css's @theme block", () => {
    const fromCss = parseThemeBlock(themeCss);
    expect(tokens).toEqual(fromCss);
  });
});
