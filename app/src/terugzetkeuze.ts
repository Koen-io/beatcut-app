import { APP_NAAM } from "./naam.ts";

// Wat de terugzetdialoog opschrijft, los van React zodat het te testen is.
// De feiten komen uit `project.kopie` (engine/cve/opruimen.py): die heeft de
// zip gelezen en op schijf gekeken of de video's er nog staan.

export type KopieBron = {
  naam: string;
  bytes: number;
  /** Waar het origineel stond bij het importeren; null als dat onbekend is. */
  oud: string | null;
  /** Waar hij nu gevonden is; null als hij ontbreekt. */
  pad: string | null;
};

export type Kopie = {
  pad: string;
  /** De naam die het project had toen de kopie gemaakt werd. */
  project: string;
  /** Onder welke naam het terugkomt — altijd een naam die nog vrij is. */
  naam: string;
  /** De gevraagde naam is al van een ander project. */
  bezet: boolean;
  gemaakt: string | null;
  beatcut: string | null;
  aantal_clips: number;
  bronnen: KopieBron[];
  /** Zitten de voorvertoningen erbij? */
  proxies: boolean;
  heeft_montage: boolean;
  heeft_muziek: boolean;
  /** Hoe groot het zip-bestand is. */
  bytes: number;
  uitgepakt: number;
};

export type Teruggezet = {
  naam: string;
  gekoppeld: string[];
  ontbreekt: string[];
  /** De voorvertoningen moeten opnieuw gemaakt worden. */
  verwerken: boolean;
};

/** De video's die niet (meer) te vinden zijn. */
export function ontbrekend(kopie: Kopie): KopieBron[] {
  return kopie.bronnen.filter((b) => b.pad === null);
}

const videos = (n: number) => (n === 1 ? "video" : "video's");

/** "4 oktober 2026 om 14:10". De kopie bewaart het moment in UTC; hier staat
 *  het in de tijd van de computer. `tijdzone` is er voor de test. */
export function datumTekst(iso: string | null, tijdzone?: string): string {
  const moment = iso === null ? NaN : Date.parse(iso);
  if (Number.isNaN(moment)) return "onbekend";
  return new Date(moment).toLocaleString("nl-NL", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tijdzone,
  });
}

/** De laatste stap van een pad, met beide soorten schuine streep. */
export function bestandsnaam(pad: string): string {
  return pad.split(/[\\/]/).filter(Boolean).pop() ?? pad;
}

export type BronnenTekst = { toon: "geen" | "ok" | "let-op"; kop: string; uitleg: string };

/** Wat er over de video's te zeggen valt. `gezocht`: de gebruiker heeft al een
 *  map aangewezen, dus "wijs aan" is dan geen nieuws meer. */
export function bronnenTekst(kopie: Kopie, gezocht = false): BronnenTekst {
  const totaal = kopie.bronnen.length;
  const mis = ontbrekend(kopie);
  if (totaal === 0) {
    return { toon: "geen", kop: "In dit project zaten geen video's.", uitleg: "" };
  }
  if (mis.length === 0) {
    return {
      toon: "ok",
      kop: totaal === 1 ? "De video is gevonden." : `Alle ${totaal} video's zijn gevonden.`,
      uitleg: `${APP_NAAM} zet ze weer in het project. Je originelen blijven waar ze zijn.`,
    };
  }
  const allemaal = mis.length === totaal;
  let kop: string;
  if (mis.every((b) => b.oud === null) && !gezocht) {
    // Een kopie van een ouder project: toen hield BeatCut de plek nog niet bij.
    kop = allemaal
      ? `${APP_NAAM} weet niet waar de ${totaal === 1 ? "video" : `${totaal} video's`} van dit project ${totaal === 1 ? "staat" : "staan"}.`
      : `Van ${mis.length} van de ${totaal} video's weet ${APP_NAAM} niet waar ze staan.`;
  } else if (gezocht) {
    kop = `Daar ${mis.length === 1 ? "is" : "zijn"} er nog ${mis.length} van de ${totaal} niet gevonden.`;
  } else if (totaal === 1) {
    kop = "De video staat niet meer waar hij stond.";
  } else if (allemaal) {
    kop = `Geen van de ${totaal} video's staat nog waar hij stond.`;
  } else {
    kop = `${mis.length} van de ${totaal} video's ${mis.length === 1 ? "staat" : "staan"} niet meer waar ${mis.length === 1 ? "hij stond" : "ze stonden"}.`;
  }
  const wijs = `Wijs de map aan waar ${mis.length === 1 ? "hij nu staat" : "ze nu staan"}.`;
  const later = `Of zet het project toch terug en sleep de ${videos(mis.length)} er later in.`;
  return {
    toon: "let-op",
    kop,
    uitleg: kopie.proxies
      ? `${wijs} ${later}`
      : `${wijs} ${later} Tot die tijd is de montage niet te bekijken.`,
  };
}

/** De regel onder het naamveld, of null als er niets te melden is. `gewenst`
 *  is wat de gebruiker intikte; null zolang hij het veld niet aanraakte. */
export function naamUitleg(kopie: Kopie, gewenst: string | null): string | null {
  const gerust = "Er wordt niets overschreven.";
  if (gewenst === null) {
    return kopie.bezet
      ? `Er staat al een project "${kopie.project}". De kopie komt ernaast, als "${kopie.naam}". ${gerust}`
      : null;
  }
  if (kopie.bezet) return `Die naam is al in gebruik. Het wordt "${kopie.naam}". ${gerust}`;
  return kopie.naam === gewenst.trim() ? null : `Het project gaat "${kopie.naam}" heten.`;
}

/** Zoveel ontbrekende video's bij naam; de rest als "en nog n". */
export const TOON_ONTBREKEND = 4;

/** De balk boven de clips van een teruggezet project dat nog video's mist. */
export function wachtTekst(namen: string[]): { kop: string; uitleg: string } {
  const een = namen.length === 1;
  const rest = namen.length - TOON_ONTBREKEND;
  const lijst = namen.slice(0, TOON_ONTBREKEND).join(", ") + (rest > 0 ? ` en nog ${rest}` : "");
  return {
    kop: een ? "Dit project wacht nog op 1 video" : `Dit project wacht nog op ${namen.length} video's`,
    uitleg:
      `${lijst}. Sleep ${een ? "hem" : "ze"} hierheen: ${APP_NAAM} zet ${een ? "hem" : "ze"} terug op ` +
      `${een ? "zijn" : "hun"} plek in de montage. Tot die tijd wordt er niets opnieuw ingelezen.`,
  };
}

/** Eén zin voor de melding na afloop. */
export function teruggezetTekst(uit: Teruggezet): string {
  const delen: string[] = [];
  const erbij = uit.gekoppeld.length;
  const mis = uit.ontbreekt.length;
  if (erbij > 0) {
    delen.push(erbij === 1 && mis === 0 ? "De video is er weer bij." : `${erbij} ${videos(erbij)} ${erbij === 1 ? "is" : "zijn"} er weer bij.`);
  }
  if (mis > 0) {
    delen.push(
      mis === 1
        ? "1 video ontbreekt nog: sleep hem in het project."
        : `${mis} video's ontbreken nog: sleep ze in het project.`,
    );
  }
  if (uit.verwerken) delen.push("De voorvertoningen worden opnieuw gemaakt.");
  return delen.join(" ");
}
