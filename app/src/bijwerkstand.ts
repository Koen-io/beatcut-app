// De regels van het bijwerken, los van React en Tauri zodat ze onder
// `node --test` te toetsen zijn. De hook in `zelf-bijwerken.ts` voert ze uit.

/** Zolang de app open staat: elke vier uur stil kijken (Koens keuze, 15-10-2026). */
export const INTERVAL_MS = 4 * 60 * 60 * 1000;
/** Hoe lang "je bent bij" blijft staan voor hij zichzelf sluit. */
export const AFTEL_MS = 4000;
/** Tussen de splash en de eerste controle: de app moet eerst staan. */
export const START_WACHT_MS = 600;

export type Controle = {
  huidige: string;
  beschikbaar: boolean;
  versie: string | null;
  notities: string | null;
  datum: string | null;
  soort: "publiek" | "prive";
};

export type Fase =
  | { soort: "rust" }
  | { soort: "zoekt" }
  | { soort: "bij"; huidige: string }
  | { soort: "nieuw"; controle: Controle }
  | { soort: "haalt"; controle: Controle; ontvangen: number; totaal: number | null }
  | { soort: "klaar"; controle: Controle }
  | { soort: "fout"; bericht: string };

/** Waarom er gecontroleerd wordt; bepaalt wat er in beeld komt. */
export type Aanleiding = "start" | "periodiek" | "hand";

/** Hoort de pop-up in beeld te staan?
 *
 *  - Bij het *starten* en *met de hand*: ja, in elke fase — je wilt zien dat
 *    er gekeken wordt en wat eruit kwam, ook "je bent bij".
 *  - *Periodiek* (elke vier uur, terwijl iemand werkt): alleen als er echt
 *    iets is. Een "je bent bij" midden in een montage is een onderbreking. */
export function toonPopup(aanleiding: Aanleiding, fase: Fase): boolean {
  if (fase.soort === "rust") return false;
  if (aanleiding === "periodiek") {
    return fase.soort === "nieuw" || fase.soort === "haalt" || fase.soort === "klaar";
  }
  return true;
}

/** Sluit de pop-up zichzelf na de afteltijd? Alleen bij "je bent bij"; al het
 *  andere vraagt een keuze of meldt een fout, en die laat je niet verdwijnen. */
export function sluitVanzelf(fase: Fase): boolean {
  return fase.soort === "bij";
}

/** De regel in het instellingenpaneel: wanneer er voor het laatst gekeken is. */
export function laatstTekst(laatst: Date | null, nu: Date = new Date()): string {
  if (laatst === null) return "nog niet gecontroleerd";
  const verschil = nu.getTime() - laatst.getTime();
  if (verschil < 60_000) return "zojuist gecontroleerd";
  if (verschil < 60 * 60_000) return `${Math.round(verschil / 60_000)} min geleden gecontroleerd`;
  const zelfdeDag = laatst.toDateString() === nu.toDateString();
  const uur = `${String(laatst.getHours()).padStart(2, "0")}:${String(laatst.getMinutes()).padStart(2, "0")}`;
  if (zelfdeDag) return `vandaag om ${uur} gecontroleerd`;
  const gisteren = new Date(nu);
  gisteren.setDate(nu.getDate() - 1);
  if (laatst.toDateString() === gisteren.toDateString()) return `gisteren om ${uur} gecontroleerd`;
  const dagen = Math.round(verschil / 86_400_000);
  return `${dagen} dagen geleden gecontroleerd`;
}

/** Percentage voor de ring tijdens het ophalen; zonder totaal pendelt hij niet
 *  maar blijft hij op 0 tot het klaar is (de ring draait dan niet rond). */
export function deel(ontvangen: number, totaal: number | null): number | null {
  if (totaal === null || totaal <= 0) return null;
  return Math.max(0, Math.min(1, ontvangen / totaal));
}

/** Een foutmelding van de engine/updater in gewone taal. */
export function foutTekst(e: unknown): string {
  const s = String(e instanceof Error ? e.message : e);
  if (/offline|network|dns|resolve|bereikbaar|connect/i.test(s)) {
    return "Geen verbinding met de updateserver. Probeer het later nog eens.";
  }
  if (/duurde te lang/i.test(s)) {
    return "De controle duurde te lang. Probeer het later nog eens.";
  }
  if (/geen release gevonden/i.test(s)) {
    return "Er staat nog geen versie klaar om op te halen.";
  }
  if (/token/i.test(s)) {
    return "Deze versie kan zichzelf niet bijwerken. Installeer een nieuwe versie met de installer.";
  }
  if (/signature|handtekening/i.test(s)) {
    return "De update is geweigerd: de handtekening klopt niet.";
  }
  return s.length > 160 ? `${s.slice(0, 157)}…` : s;
}
