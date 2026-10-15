// Sneltoetsen in stap 4. Pure functie, los van React, zodat
// app/tests/monteertoets.test.ts hem zonder browser toetst.
//
//   ⌘Z / Ctrl+Z            ongedaan
//   ⇧⌘Z / Ctrl+Y / ⇧Ctrl+Z  opnieuw
//   S                      knippen op de afspeelkop (of midden van het shot)
//   ⌫ / Delete             shot weghalen
//   ,  /  .                snede aan het eind van het shot een tel terug / vooruit
//   ⌥← / ⌥→                vorig / volgend shot kiezen
//
// Wat níét van ons is (spatie: de speler; pijltjes zonder ⌥: de scrubbalk)
// geeft `null`, en dan mag de rest van de app de toets hebben.

export type Monteeractie =
  | "ongedaan"
  | "opnieuw"
  | "splits"
  | "verwijder"
  | "snede-terug"
  | "snede-vooruit"
  | "vorig-shot"
  | "volgend-shot";

export type Toets = {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
};

export function monteeractie(e: Toets): Monteeractie | null {
  const cmd = !!(e.metaKey || e.ctrlKey);
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (cmd) {
    if (k === "z") return e.shiftKey ? "opnieuw" : "ongedaan";
    if (k === "y") return "opnieuw";
    return null; // ⌘S, ⌘C… horen bij de app of het systeem
  }
  if (e.altKey) {
    if (k === "ArrowLeft") return "vorig-shot";
    if (k === "ArrowRight") return "volgend-shot";
    return null;
  }
  switch (k) {
    case "s":
      return "splits";
    case "Backspace":
    case "Delete":
      return "verwijder";
    case ",":
      return "snede-terug";
    case ".":
      return "snede-vooruit";
    default:
      return null;
  }
}

/** Mag deze toets bij ons langs? Niet als iemand in een veld typt. */
export function typtInVeld(doel: { tagName?: string; isContentEditable?: boolean } | null): boolean {
  if (!doel) return false;
  if (doel.isContentEditable) return true;
  return /^(INPUT|TEXTAREA|SELECT)$/.test(doel.tagName ?? "");
}
