// Welke editie dit is: BeatCut, of een merk dat dezelfde app onder een eigen
// naam draait (app/edities/LEESMIJ.md). Eén import, alles wat de interface
// over het merk moet weten: naam, motto, logo, hoe hij zich bijwerkt.
//
// `@editie` is een Vite-alias naar `app/edities/<BEATCUT_EDITIE>/`. Daardoor
// zit alleen het gekozen merk in de bundel — het logo van de ene editie komt
// nooit in de app van de andere terecht.
import gegevens from "@editie/editie.json";
import "@editie/editie.css";
import { zetAppNaam } from "./naam";

export type Editie = {
  /** Mapnaam en sleutel: "beatcut", "p-alv". */
  id: string;
  /** Volledige naam, zoals in de titelbalk en op de splash. */
  naam: string;
  /** Korte naam voor krappe plekken. */
  kort: string;
  /** De regel onder de naam op de splash. */
  ondertitel: string;
  /** Lijfspreuk, klein onder de ondertitel; null = geen. */
  motto: string | null;
  /** De regel onder de projectnaam in de titelbalk. */
  regel: string;
  /** Bestandsnaam van het beeldmerk in de editiemap; null = de BeatCut-balkjes. */
  logo: string | null;
  updates: {
    /** "publiek": latest.json rechtstreeks van GitHub Releases;
     *  "prive": via de GitHub-API met het ingebakken token (lib.rs). */
    soort: "publiek" | "prive";
    repo: string;
  };
};

export const EDITIE: Editie = gegevens as Editie;
zetAppNaam(EDITIE.naam);

/** Het logo als URL voor een <img>, of null als deze editie de balkjes toont.
 *  Vite's glob zorgt dat alleen het bestand uit de gekozen editiemap meegaat. */
const logos = import.meta.glob("@editie/logo.png", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
export const LOGO_URL: string | null = EDITIE.logo === null ? null : (Object.values(logos)[0] ?? null);

/** Of dit de standaardeditie is. Teksten die BeatCut bij naam noemen als
 *  product (niet als app) blijven alleen daar staan. */
export const IS_BEATCUT = EDITIE.id === "beatcut";
