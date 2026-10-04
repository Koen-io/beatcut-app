// Getallen naar tekst. Eén plek, want Media, Stijl en Exporteren tellen
// allemaal dezelfde seconden en bytes af.

/** Seconden als m:ss. */
export function duurTekst(seconden: number): string {
  const heel = Math.round(seconden);
  return `${Math.floor(heel / 60)}:${String(heel % 60).padStart(2, "0")}`;
}

/** Bytes in MB of GB, met een komma zoals het hier hoort. */
export function bytesTekst(bytes: number): string {
  const mb = bytes / 1_000_000;
  return mb >= 1000
    ? `${(mb / 1000).toFixed(1).replace(".", ",")} GB`
    : `${Math.round(mb)} MB`;
}

/** Een getal met een decimale komma. Nederlands schrijft 0,74, niet 0.74. */
export function getal(waarde: number, decimalen = 2): string {
  return waarde.toFixed(decimalen).replace(".", ",");
}
