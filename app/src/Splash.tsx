// Het eerste wat iemand van BeatCut ziet. Hij staat er bij elke start, en bij
// de allereerste start toont hij ook wat er binnengehaald wordt.
//
// **Waarom het logo op de beat loopt.** Dat is wat BeatCut doet en waar de
// naam vandaan komt: elke snede ligt op de tel. Vijf balkjes die allemaal
// hetzelfde doen zijn een laadanimatie; vijf balkjes die elk op hun eigen
// onderverdeling bewegen — een hele tel, een halve, twee tellen — leest als
// muziek. Elke twee tellen vallen ze samen op de kick, en dat is het moment
// waarop de gloed erachter oplicht.
//
// **Waarom CSS en geen JavaScript.** Precies tijdens deze animatie start de
// engine op, leest de app zijn instellingen en bouwt React zijn boom. Een
// animatie op `requestAnimationFrame` laat daar frames vallen; een
// CSS-animatie draait buiten de hoofddraad om en blijft vloeiend. Zie
// `app/src/styles.css`, blok "splash".
//
// **Hij blijft niet langer staan dan nodig** — zodra de engine antwoordt gaat
// hij weg, met één tel als ondergrens zodat het geen flits wordt.
import { useEffect, useState } from "react";

import { EDITIE, LOGO_URL } from "./editie";
import { bytesTekst } from "./format";
import type { OnderdelenStand } from "./onderdelen";

/** Het tempo van de animatie. 120 BPM is een halve seconde per tel — snel
 *  genoeg om in een opstart van een seconde twee keer te pulsen, rustig genoeg
 *  om als muziek te lezen en niet als een trilling. */
export const TEL_MS = 500;
/** Ondergrens voor hoe lang de splash blijft staan: vier tellen, twee keer
 *  de kick. Eén tel bleek in de praktijk onzichtbaar — de engine antwoordt
 *  binnen een halve seconde, dus Koen zag bij het openen géén splash
 *  (04-10-2026). Vier tellen laat het logo één keer echt spelen en eindigt
 *  op de kick. */
export const MINSTENS_MS = 4 * TEL_MS;
/** Hoe lang het wegvallen duurt. Onder de 300 ms, zoals alles in deze app. */
export const WEG_MS = 260;

/** Staat op elke splash onder de naam, wat er verder ook te melden is. */
export const ONDERTITEL = EDITIE.ondertitel;

export type SplashStand =
  /** De engine start nog. */
  | { soort: "starten" }
  /** Eerste start: er wordt iets opgehaald dat de app nodig heeft. */
  | { soort: "installeren"; onderdelen: OnderdelenStand; bytes: number; nodig: number }
  | { soort: "fout"; bericht: string };

type Props = {
  stand: SplashStand;
  /** Waar tijdens het wegvallen; zet de afscheidsanimatie aan. */
  uit?: boolean;
  /** Of het muziekmodel op de achtergrond binnenkomt. Blokkeert niets — de app
   *  is bruikbaar en muziek genereren wordt beschikbaar zodra het er is. */
  muziekOpDeAchtergrond: boolean;
  /** Overslaan en doorgaan; de download loopt op de achtergrond door. */
  onOverslaan?: () => void;
  onOpnieuw?: () => void;
};

export default function Splash({
  stand,
  uit = false,
  muziekOpDeAchtergrond,
  onOverslaan,
  onOpnieuw,
}: Props) {
  const bezig = stand.soort === "installeren" && stand.onderdelen.soort === "bezig";
  const percentage = bezig && stand.soort === "installeren"
    ? (stand.onderdelen as { percentage: number }).percentage
    : 0;

  const tekst = regel(stand);

  return (
    <div className={`splash${uit ? " uit" : ""}`} role="status" aria-live="polite">
      <div className="splash-midden">
        <Merk />
        <p className="splash-ondertitel">{ONDERTITEL}</p>
        {EDITIE.motto !== null && <p className="splash-motto">{EDITIE.motto}</p>}
        {/* Staat alles er al, dan is er niets te melden: alleen het merk. Een
            regel en een balk verschijnen pas als er echt iets geladen wordt. */}
        {tekst !== null && <p className="splash-regel">{tekst}</p>}

        {stand.soort === "installeren" && (
          <div className="splash-werk">
            <div className="voortgangsbalk">
              <div
                className={`vulling${bezig ? "" : " pendelt"}`}
                style={{ "--deel": percentage / 100 } as React.CSSProperties}
              />
            </div>
            <div className="splash-cijfers mono">
              <span>{stand.onderdelen.soort === "bezig" ? stand.onderdelen.tekst : "Klaarzetten…"}</span>
              <span>
                {stand.nodig > 0
                  ? `${bytesTekst(stand.bytes)} van ${bytesTekst(stand.nodig)}`
                  : bytesTekst(stand.bytes)}
              </span>
            </div>
            <div className="splash-knoppen">
              {stand.onderdelen.soort === "fout" && onOpnieuw !== undefined && (
                <button className="knop-licht" onClick={onOpnieuw}>
                  Opnieuw proberen
                </button>
              )}
              {onOverslaan !== undefined && (
                <button className="knop-stil" onClick={onOverslaan}>
                  Overslaan en beginnen
                </button>
              )}
            </div>
            {stand.onderdelen.soort === "fout" && (
              <p className="splash-fout mono">{stand.onderdelen.bericht}</p>
            )}
          </div>
        )}

        {stand.soort === "fout" && <p className="splash-fout mono">{stand.bericht}</p>}

        {muziekOpDeAchtergrond && (
          <p className="splash-voetnoot">
            Muziek maken wordt op de achtergrond klaargezet. Je kunt intussen gewoon beginnen.
          </p>
        )}
      </div>
    </div>
  );
}

/** De statusregel onder het merk; `null` als er niets geladen wordt. */
export function regel(stand: SplashStand): string | null {
  if (stand.soort === "fout") return "De engine kwam niet op gang";
  if (stand.soort === "starten") return null;
  if (stand.onderdelen.soort === "fout") return "Dat ophalen ging niet goed";
  return "Even klaarzetten — dit gebeurt alleen de eerste keer";
}

/** Het merk: vijf balkjes die op de tel lopen, met de naam ernaast.
 *
 *  De balkjes zijn dezelfde vijf als in de titelbalk (`App.tsx`), alleen groot
 *  en in beweging. Elk balkje heeft een eigen onderverdeling — zie de
 *  CSS-klassen `b1` tot en met `b5`. */
function Merk() {
  if (LOGO_URL !== null) {
    // Een editie met een eigen beeldmerk: het logo groot, met de gloed erachter
    // op dezelfde tel als de balkjes. De twee lichtpunten liggen op de ogen
    // van het beeldmerk (gemeten: 27,5 % en 72 % van de breedte, 45 % hoog).
    return (
      <div className="splash-merk splash-merk-logo">
        <div className="splash-beeldmerk" aria-hidden="true">
          <span className="gloed" />
          <span className="ring" />
          <img src={LOGO_URL} alt="" draggable={false} />
          <span className="oog links" />
          <span className="oog rechts" />
        </div>
        <h1 className="splash-naam">{EDITIE.naam}</h1>
      </div>
    );
  }
  return (
    <div className="splash-merk">
      <div className="splash-balken" aria-hidden="true">
        <span className="gloed" />
        <span className="balkje b1" />
        <span className="balkje b2" />
        <span className="balkje b3" />
        <span className="balkje b4" />
        <span className="balkje b5" />
      </div>
      <h1 className="splash-naam">{EDITIE.naam}</h1>
    </div>
  );
}

/** Houdt de splash in beeld tot de app klaar is én de ondergrens voorbij is,
 *  en laat hem daarna uitfaden.
 *
 *  Geeft `null` terug zodra hij helemaal weg mag; `uit` is waar tijdens het
 *  wegvallen, zodat de laag nog één keer getekend wordt met de afscheidsklasse
 *  erop. */
export function useSplash(klaar: boolean): { zichtbaar: boolean; uit: boolean } {
  const [begon] = useState(() => Date.now());
  const [zichtbaar, setZichtbaar] = useState(true);
  const [uit, setUit] = useState(false);

  useEffect(() => {
    // Terug naar zichtbaar als er tóch weer gewacht moet worden. Zonder dit
    // bleef `uit` aan staan terwijl de opruimtimer geannuleerd werd: een
    // onzichtbare splash over de app, die alle muisklikken opving en nergens
    // meer vandaan ging. Gevonden in de tegenlezing van 04-10-2026, met de
    // onderdeleninstallatie die precies tijdens het uitfaden begint.
    if (!klaar) {
      setUit(false);
      return;
    }
    const wacht = Math.max(0, MINSTENS_MS - (Date.now() - begon));
    const a = setTimeout(() => setUit(true), wacht);
    const b = setTimeout(() => setZichtbaar(false), wacht + WEG_MS);
    return () => {
      clearTimeout(a);
      clearTimeout(b);
    };
  }, [klaar, begon]);

  return { zichtbaar, uit };
}
