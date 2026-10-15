// node --test app/tests/titelbereik.test.ts  (Node 24 leest TypeScript zelf)
//
// De titelcompositie (`brands/sjablonen/titel20.css`) draait in het
// app-document, niet in een iframe (zie `src/speler/Titels.tsx`). Twee
// stylesheets met korte Nederlandse klassenamen in één document: dat botste al
// eens — `.balk` uit het sjabloon zette elke voortgangsbalk van de app op
// `display: none` (04-10-2026), en `.kaart` kleurde de clipkaarten wit.
//
// Twee kanten, twee sloten:
//   - sjabloon -> app: de bouw zet het hele sjabloon binnen `.titel20-laag`
//     (`titelbereik.ts`), dus daarbuiten raakt het niets meer.
//   - app -> sjabloon: geen regel van de app mag alleen uit klassenamen van het
//     sjabloon bestaan, want dan grijpt hij ook ín de titel en wijkt de
//     voorvertoning af van de export.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { TITELLAAG, binnenTitellaag, isTitelsjabloon } from "../titelbereik.ts";

const lees = (pad: string) =>
  readFileSync(fileURLToPath(new URL(pad, import.meta.url)), "utf-8");

const sjabloon = lees("../../brands/sjablonen/titel20.css");
const app = lees("../src/styles.css");

const zonderCommentaar = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

/** Wat er vóór elke `{` staat: de selectors, en de koppen van @-regels. */
const koppen = (css: string) =>
  [...zonderCommentaar(css).matchAll(/([^{}]+)\{/g)].map((m) => m[1].trim());

const selectors = (css: string) =>
  koppen(css)
    .filter((k) => !k.startsWith("@"))
    .flatMap((k) => k.split(",").map((s) => s.trim()))
    .filter(Boolean);

const klassen = (selector: string) =>
  [...selector.matchAll(/\.([a-zA-Z_][\w-]*)/g)].map((m) => m[1]);

test("het sjabloon komt in zijn geheel binnen de titellaag te staan", () => {
  const uit = binnenTitellaag(sjabloon);
  assert.ok(uit.startsWith(`${TITELLAAG}{`));
  assert.ok(uit.trimEnd().endsWith("}"));
  assert.ok(uit.includes(sjabloon));
  const open = (zonderCommentaar(uit).match(/\{/g) ?? []).length;
  const dicht = (zonderCommentaar(uit).match(/\}/g) ?? []).length;
  assert.equal(open, dicht);
});

test("alleen titel20.css wordt ingeperkt, niet de lettertypes of de app", () => {
  assert.equal(isTitelsjabloon("/x/brands/sjablonen/titel20.css"), true);
  assert.equal(isTitelsjabloon("/x/brands/sjablonen/titel20.css?direct"), true);
  assert.equal(isTitelsjabloon("C:\\x\\brands\\sjablonen\\titel20.css"), true);
  assert.equal(isTitelsjabloon("/x/brands/fonts/titelfonts.css"), false);
  assert.equal(isTitelsjabloon("/x/brands/sjablonen/titel20.js?url"), false);
  assert.equal(isTitelsjabloon("/x/app/src/styles.css"), false);
});

test("het sjabloon is in te perken: alleen regels die met een class beginnen", () => {
  // Een @-regel (@font-face, @keyframes, @import) werkt niet genest, en een
  // selector die met een elementnaam begint evenmin in oudere WebKit.
  const atRegels = koppen(sjabloon).filter((k) => k.startsWith("@"));
  assert.deepEqual(atRegels, []);
  const fout = selectors(sjabloon).filter((s) => !s.startsWith("."));
  assert.deepEqual(fout, []);
});

test("geen regel van de app grijpt in de titelcompositie", () => {
  const vanSjabloon = new Set(selectors(sjabloon).flatMap(klassen));
  const fout = selectors(app).filter((s) => {
    const k = klassen(s);
    return k.length > 0 && k.every((naam) => vanSjabloon.has(naam));
  });
  assert.deepEqual(fout, []);
});
