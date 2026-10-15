// De rekenkunde achter de sleepbare kolommen, los van React zodat hij te
// testen is. Zie `Zijbalk.tsx` voor de kolom zelf.

export type Kant = "links" | "rechts";

/** Hoeveel een pijltjestoets verschuift, en met shift erbij. */
export const STAP = 16;
export const GROTE_STAP = 64;

/** Smalste kolom die nog iets zinnigs toont: de projectlijst in stap 1 met een
 *  naam en een aantal erachter. Smaller wordt het een strookje met afgekapte
 *  tekst, en dan is "verslepen" een manier om de app te slopen. */
export const MIN = 180;

/** Hoeveel een kolom hoogstens mag krimpen ten opzichte van het ontwerp.
 *
 *  Eén vast minimum van 180 px werkt niet voor alle zeven: de stijlkaarten in
 *  stap 2 hebben een tegel van 124 px links, en op 180 px bleef er 24 px over
 *  voor de titel en het snijritme — onleesbaar (gemeten 04-10-2026). Wat de
 *  smalste kolom aankan is nu eenmaal niet wat de breedste aankan, en de
 *  ontwerpbreedte is de beste maat die we daarvoor hebben. */
const MIN_FACTOR = 0.7;

/** Hoeveel breder dan het ontwerp een kolom mag worden. De breedste kolom
 *  (Exporteren, 420 px) komt daarmee op 630 px. */
const MAX_FACTOR = 1.5;

/** En hoeveel van het venster één kolom hoogstens mag pakken. Een derde, want
 *  stap 2 en stap 3 hebben er twéé: op 40 % elk bleef er van een venster van
 *  1400 px nog 390 px midden over (gemeten 04-10-2026). Op een derde elk houdt
 *  het midden altijd ten minste een derde. Dit moet van hier komen en niet van
 *  de kolom zelf: een kolom weet niet hoe breed zijn tegenhanger staat. */
const MAX_DEEL_VENSTER = 1 / 3;

/** De grenzen voor een kolom met deze standaardbreedte, in pixels.
 *
 *  `vensterbreedte` is er voor de tests; in de app komt hij uit het venster. */
export function breedteGrenzen(
  standaard: number,
  vensterbreedte: number = typeof window === "undefined" ? 1600 : window.innerWidth,
): [number, number] {
  const krap = Math.max(MIN, Math.round(standaard * MIN_FACTOR));
  const ruim = Math.round(standaard * MAX_FACTOR);
  const past = Math.round(vensterbreedte * MAX_DEEL_VENSTER);
  // Nooit onder de ondergrens uitkomen, ook niet op een heel smal venster:
  // dan is de bovengrens kleiner dan de ondergrens en klapt het klemmen om.
  return [krap, Math.max(krap, Math.min(ruim, past))];
}

/** Wat een toetsaanslag met de breedte doet, of null als de toets niets doet.
 *
 *  Rechterkolommen groeien naar links: daar maakt de pijl naar links breder.
 *  Dat is wat de hand verwacht — de greep beweegt mee met de pijl. */
export function nieuweBreedte(
  toets: string,
  shift: boolean,
  huidig: number,
  standaard: number,
  kant: Kant,
): number | null {
  if (toets === "Home" || toets === "Enter" || toets === " ") return standaard;
  const stap = shift ? GROTE_STAP : STAP;
  const heen = kant === "links" ? 1 : -1;
  if (toets === "ArrowRight") return huidig + stap * heen;
  if (toets === "ArrowLeft") return huidig - stap * heen;
  return null;
}

const VOORVOEGSEL = "beatcut.kolom.";

/** De bewaarde breedte, geklemd binnen de grenzen van nu.
 *
 *  Alles kan hier mis zijn: geen opslag (privémodus), rommel van een oudere
 *  versie, of een breedte die op een groter venster bewaard is. Geen van die
 *  gevallen mag de app een onbruikbare kolom geven. */
export function lees(
  sleutel: string,
  standaard: number,
  vensterbreedte?: number,
): number {
  const [min, max] = breedteGrenzen(standaard, vensterbreedte);
  let ruw: string | null = null;
  try {
    ruw = localStorage.getItem(VOORVOEGSEL + sleutel);
  } catch {
    return standaard;
  }
  if (ruw === null) return Math.min(max, Math.max(min, standaard));
  const n = Number(ruw);
  if (!Number.isFinite(n)) return Math.min(max, Math.max(min, standaard));
  return Math.round(Math.min(max, Math.max(min, n)));
}

export function schrijf(sleutel: string, breedte: number): void {
  try {
    localStorage.setItem(VOORVOEGSEL + sleutel, String(Math.round(breedte)));
  } catch {
    // Privémodus of volle opslag. De breedte van een kolom is geen reden om
    // iets te melden; hij staat deze sessie goed en begint volgende keer
    // opnieuw bij de standaard.
  }
}
