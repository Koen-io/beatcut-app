import { APP_NAAM } from "./naam.ts";

// Wat de verwijderdialoog uitrekent, los van React zodat het te testen is.
// De getallen komen uit `project.omvang` (engine/cve/opruimen.py) en zijn
// gemeten; hier wordt alleen opgeteld en opgeschreven.

/** Wat de gebruiker kan kiezen te houden. `werk` hoort er niet bij: dat is het
 *  project zelf en gaat altijd weg. Spiegelt `opruimen.KEUZES`. */
export const KEUZESOORTEN = ["kopieen", "muziek", "exports"] as const;
export type Keuzesoort = (typeof KEUZESOORTEN)[number];
export type Soort = "werk" | Keuzesoort;

export type Omvang = {
  naam: string;
  aantal_clips: number;
  soorten: Record<Soort, { bytes: number; bestanden: number }>;
  totaal: number;
  /** Hoe groot de kopie-zip wordt: zonder en de toeslag voor proxies. */
  kopie: { basis: number; proxies: number };
  /** Loopt er werk voor dit project, dan staat hier wat. */
  bezig: string | null;
  /** "Prullenmand" op de Mac, "Prullenbak" op Windows. */
  prullenbak: string;
  /** Waar terechtkomt wat je houdt. */
  bewaard: string;
};

/** Per keuzesoort: gaat hij mee weg? */
export type Keuze = Record<Keuzesoort, boolean>;

/** Exports wil je vaak houden; de rest is wat BeatCut zelf neerzette. */
export const STANDAARD: Keuze = { kopieen: true, muziek: true, exports: false };

export const SOORT_TEKST: Record<Soort, { titel: string; uitleg: string }> = {
  werk: {
    titel: "Montage, analyse en voorvertoningen",
    uitleg: "Dit is het project zelf. Gaat altijd mee.",
  },
  kopieen: {
    titel: "Geïmporteerde kopieën van je video's",
    uitleg: `De kopie die ${APP_NAAM} bij het importeren maakte — niet je origineel.`,
  },
  muziek: { titel: "Muziek", uitleg: "Het nummer onder dit project." },
  exports: { titel: "Geëxporteerde video's", uitleg: "De video's die je met dit project maakte." },
};

/** De soorten die in `weg` naar de engine gaan. */
export function wegLijst(keuze: Keuze): Keuzesoort[] {
  return KEUZESOORTEN.filter((s) => keuze[s]);
}

/** Hoeveel bytes er naar de prullenbak gaan. */
export function gaatWeg(omvang: Omvang, keuze: Keuze): number {
  return wegLijst(keuze).reduce((som, s) => som + omvang.soorten[s].bytes, omvang.soorten.werk.bytes);
}

/** Hoeveel er bewaard blijft. Samen met `gaatWeg` altijd het totaal. */
export function blijft(omvang: Omvang, keuze: Keuze): number {
  return omvang.totaal - gaatWeg(omvang, keuze);
}

/** Bytes als tekst, ook onder de megabyte. `bytesTekst` in format.ts rondt op
 *  hele MB af, en dan staat er "0 MB" bij een montage van 40 kB — dat leest
 *  als "er is niets". */
export function grootteTekst(bytes: number): string {
  if (bytes <= 0) return "leeg";
  if (bytes < 1000) return "< 1 kB";
  if (bytes < 1_000_000) return `${Math.round(bytes / 1000)} kB`;
  const mb = bytes / 1_000_000;
  if (mb < 10) return `${mb.toFixed(1).replace(".", ",")} MB`;
  if (mb < 1000) return `${Math.round(mb)} MB`;
  return `${(mb / 1000).toFixed(1).replace(".", ",")} GB`;
}

export function kopieGrootte(omvang: Omvang, metProxies: boolean): number {
  return omvang.kopie.basis + (metProxies ? omvang.kopie.proxies : 0);
}

/** Voorstel voor de bestandsnaam van de kopie. */
export function kopieNaam(project: string, vandaag: Date = new Date()): string {
  const dag = [
    vandaag.getFullYear(),
    String(vandaag.getMonth() + 1).padStart(2, "0"),
    String(vandaag.getDate()).padStart(2, "0"),
  ].join("-");
  return `${project} (${APP_NAAM}-kopie ${dag}).zip`;
}

/** Het pad van de bewaarmap als kruimelpad, alleen het stuk dat iets zegt:
 *  `…/Movies/BeatCut/_Bewaard/test` → `BeatCut › _Bewaard › test`. */
export function kruimelpad(pad: string, delen = 3): string {
  return pad.split(/[\\/]/).filter(Boolean).slice(-delen).join(" › ");
}
