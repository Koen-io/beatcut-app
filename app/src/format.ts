// Getallen naar tekst. Eén plek, want Media, Stijl en Exporteren tellen
// allemaal dezelfde seconden en bytes af.

/** Seconden als m:ss. */
export function duurTekst(seconden: number): string {
  const heel = Math.round(seconden);
  return `${Math.floor(heel / 60)}:${String(heel % 60).padStart(2, "0")}`;
}

/** Een schatting afronden zodat hij niet elke seconde van gedachten verandert.
 *
 *  Een getal dat per tel wisselt leest als een gok, ook als het klopt. Vijf
 *  seconden stappen onder de minuut en tien erboven schuiven langzaam genoeg
 *  op om als meting te lezen, en snel genoeg om te zien dat er voortgang is. */
export function ongeveerTekst(seconden: number): string {
  const stap = seconden < 60 ? 5 : 10;
  return duurTekst(Math.round(seconden / stap) * stap);
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
