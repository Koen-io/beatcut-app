// De titelcompositie binnen haar eigen laag houden.
//
// `src/speler/Titels.tsx` laadt `brands/sjablonen/titel20.css` in het
// app-document, omdat de compositie daar draait en niet in een iframe. Dat
// sjabloon is geschreven voor een document waar het alleen staat: `.kaart`,
// `.balk`, `.regel`, `.titel`, `.onder`. In de app golden die regels overal —
// `.balk` zette elke voortgangsbalk op `display: none` en `.kaart` kleurde de
// clipkaarten wit (04-10-2026).
//
// Daarom zet de bouw het hele sjabloon binnen `.titel20-laag` (CSS-nesting).
// Het bestand in `brands/` blijft zoals het is: de render gebruikt hetzelfde
// bestand, en daar staat het wél alleen in zijn document.
//
// Voorwaarde: het sjabloon heeft alleen regels die met een class beginnen en
// geen @-regels. `tests/titelbereik.test.ts` bewaakt dat.
import type { Plugin } from "vite";

/** De laag waar de titelcompositie in staat; zie `src/speler/Titels.tsx`. */
export const TITELLAAG = ".titel20-laag";

export function isTitelsjabloon(id: string): boolean {
  return id.split("?")[0].replace(/\\/g, "/").endsWith("/brands/sjablonen/titel20.css");
}

export function binnenTitellaag(css: string): string {
  return `${TITELLAAG}{\n${css}\n}\n`;
}

export function titelBinnenLaag(): Plugin {
  return {
    name: "beatcut:titel-binnen-laag",
    enforce: "pre",
    transform(code, id) {
      if (!isTitelsjabloon(id)) return null;
      return { code: binnenTitellaag(code), map: null };
    },
  };
}
