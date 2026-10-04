import { useCallback, useEffect, useRef, useState } from "react";
import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { engineBezig } from "./engine";

/** Elke 6 uur opnieuw kijken, zoals PLAN-v2.md §6 vraagt. */
const INTERVAL_MS = 6 * 60 * 60 * 1000;
/** Hoe vaak we de engine vragen of er nog werk loopt, zolang de melding staat. */
const BEZIG_MS = 3000;

export type BijwerkStand =
  | { soort: "niets" }
  | { soort: "ophalen"; versie: string }
  | { soort: "klaar"; versie: string };

/**
 * Kijkt of er een nieuwe BeatCut is, haalt hem stil op en meldt pas dat hij
 * klaarstaat. De handtekening wordt door de updater zelf gecontroleerd: een
 * bundel die niet met onze sleutel ondertekend is komt nooit verder dan
 * `download()` en belandt hier als een fout in de console.
 *
 * **Ophalen en installeren zijn twee aparte stappen, en dat is geen detail.**
 * `downloadAndInstall()` installeert meteen, en op Windows sluit de updater de
 * app daarbij af (`std::process::exit(0)`). Gebeurde dat tijdens een render,
 * een analyse of een muziekgeneratie, dan was dat werk weg. Daarom: alleen
 * `download()` op de achtergrond, en `install()` pas na een klik op
 * "Nu herstarten" — en alleen als de engine zegt dat er niets loopt.
 *
 * `online` false → helemaal geen netwerk.
 */
export function useBijwerken(online: boolean) {
  const [stand, setStand] = useState<BijwerkStand>({ soort: "niets" });
  const [weggeklikt, setWeggeklikt] = useState(false);
  /** Wat de engine nu aan het doen is, of null als er niets loopt. */
  const [bezigMet, setBezigMet] = useState<string | null>(null);
  // Twee keer tegelijk downloaden heeft geen zin en overschrijft hetzelfde bestand.
  const loopt = useRef(false);
  // De opgehaalde update blijft hier wachten tot de gebruiker herstart.
  const klaarstaand = useRef<Update | null>(null);

  useEffect(() => {
    if (!online) return;
    let gestopt = false;

    async function kijk() {
      if (loopt.current || gestopt || klaarstaand.current !== null) return;
      loopt.current = true;
      try {
        const update: Update | null = await check();
        if (update === null || gestopt) return;
        setStand({ soort: "ophalen", versie: update.version });
        await update.download();
        if (gestopt) return;
        klaarstaand.current = update;
        setStand({ soort: "klaar", versie: update.version });
        setWeggeklikt(false);
      } catch (e) {
        // Geen internet, een endpoint dat 404 geeft of een handtekening die niet
        // klopt: in alle drie de gevallen gaat de app gewoon door.
        console.warn("bijwerken overgeslagen:", e);
        setStand({ soort: "niets" });
      } finally {
        loopt.current = false;
      }
    }

    void kijk();
    const tik = setInterval(() => void kijk(), INTERVAL_MS);
    return () => {
      gestopt = true;
      clearInterval(tik);
    };
  }, [online]);

  // Pas pollen zodra de melding er staat: daarvóór doet het antwoord niets.
  const zichtbaar = stand.soort === "klaar" && !weggeklikt;
  useEffect(() => {
    if (!zichtbaar) return;
    let gestopt = false;
    async function kijk() {
      try {
        const uit = await engineBezig();
        if (!gestopt) setBezigMet(uit.bezig ? uit.werk[0].tekst : null);
      } catch {
        // Engine onbereikbaar: dan is herstarten juist ongevaarlijk.
        if (!gestopt) setBezigMet(null);
      }
    }
    void kijk();
    const tik = setInterval(() => void kijk(), BEZIG_MS);
    return () => {
      gestopt = true;
      clearInterval(tik);
    };
  }, [zichtbaar]);

  const herstart = useCallback(async () => {
    const update = klaarstaand.current;
    if (update === null) return;
    // Nog één keer vragen, nu pas echt: tussen de laatste poll en deze klik
    // kan er werk gestart zijn, en install() is op Windows onomkeerbaar.
    try {
      const uit = await engineBezig();
      if (uit.bezig) {
        setBezigMet(uit.werk[0].tekst);
        return;
      }
    } catch {
      // Engine onbereikbaar — dan loopt er ook geen render.
    }
    await update.install();
    // Windows komt hier niet: install() sluit de app daar zelf af.
    await relaunch();
  }, []);

  return {
    stand,
    zichtbaar,
    bezigMet,
    magHerstarten: bezigMet === null,
    herstart,
    verberg: () => setWeggeklikt(true),
  };
}
