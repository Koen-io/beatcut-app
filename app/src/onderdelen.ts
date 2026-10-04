import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  GEBEURTENIS,
  onderdelenInstalleer,
  onderdelenInstalleerStop,
  onderdelenStatus,
  type EngineGebeurtenis,
  type OnderdelenStatus,
} from "./engine";

export type OnderdelenStand =
  | { soort: "kijken" }
  | { soort: "klaar" }
  | { soort: "mist" }                                        // offline, of nog niet begonnen
  | { soort: "bezig"; percentage: number; tekst: string }
  | { soort: "fout"; bericht: string };

/**
 * Zorgt dat de export titels kan tekenen: node, HyperFrames en een headless
 * browser.
 *
 * **Waarom dit automatisch gaat.** De live speler tekent titels zelf; de
 * export laat een browser de compositie renderen. Ontbreekt die browser, dan
 * kwam er stil een video zonder titels uit terwijl de voorvertoning ze wél
 * toonde. Dat is de ene belofte die niet mag breken, en het is niet iets
 * waarvoor een gebruiker eerst een knop hoort te zoeken: is er internet en
 * mist er iets, dan haalt BeatCut het op de achtergrond op.
 *
 * **Offline doet hij niets** — ook geen stille poging die dertig seconden op
 * een timeout staat te wachten. Dan meldt de chip alleen dat dit eenmalig
 * internet vraagt.
 */
export function useOnderdelen(online: boolean) {
  const [status, setStatus] = useState<OnderdelenStatus | null>(null);
  const [stand, setStand] = useState<OnderdelenStand>({ soort: "kijken" });
  // Eén poging per sessie starten we zelf; daarna is het aan de gebruiker.
  // Zonder dit begint hij opnieuw zodra `online` omgezet wordt en weer terug.
  const vanzelfGeprobeerd = useRef(false);

  const lees = useCallback(async () => {
    const s = await onderdelenStatus();
    setStatus(s);
    return s;
  }, []);

  const start = useCallback(async () => {
    setStand({ soort: "bezig", percentage: 0, tekst: "Beginnen…" });
    try {
      // `gestart: false` betekent dat er al een installatie liep; de balk is
      // dan ook goed, want die voortgang komt hier binnen.
      await onderdelenInstalleer();
    } catch (e) {
      setStand({ soort: "fout", bericht: String(e) });
    }
  }, []);

  const stop = useCallback(async () => {
    try {
      await onderdelenInstalleerStop();
    } catch (e) {
      setStand({ soort: "fout", bericht: String(e) });
    }
  }, []);

  useEffect(() => {
    let gestopt = false;
    (async () => {
      try {
        const s = await lees();
        if (gestopt) return;
        if (s.alles_klaar) {
          setStand({ soort: "klaar" });
          return;
        }
        if (s.bezig) {
          setStand({ soort: "bezig", percentage: 0, tekst: "Bezig…" });
          return;
        }
        if (!online) {
          setStand({ soort: "mist" });
          return;
        }
        if (vanzelfGeprobeerd.current) {
          setStand({ soort: "mist" });
          return;
        }
        vanzelfGeprobeerd.current = true;
        await start();
      } catch (e) {
        // Engine nog niet bereikbaar: geen chip, geen paniek. Het engine-paneel
        // meldt dat al.
        if (!gestopt) setStand({ soort: "fout", bericht: String(e) });
      }
    })();
    return () => {
      gestopt = true;
    };
  }, [online, lees, start]);

  useEffect(() => {
    const af = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.werk !== "onderdelen") return;
      if (payload.gebeurtenis === "voortgang") {
        setStand({
          soort: "bezig",
          percentage: payload.data.percentage ?? 0,
          tekst: payload.data.tekst,
        });
      } else if (payload.gebeurtenis === "klaar") {
        setStand({ soort: "klaar" });
        void lees().catch(() => {});
      } else {
        setStand({ soort: "fout", bericht: payload.data.fout });
        void lees().catch(() => {});
      }
    });
    return () => {
      void af.then((f) => f());
    };
  }, [lees]);

  /** De tekst op de chip in de titelbalk, of null als er niets te melden is.
   *
   *  Kort houden: de titelbalk heeft naast de stappenbalk en de engine-chip
   *  maar een paar centimeter over, en een chip die over drie regels uitwaaiert
   *  leest als een storing. De hele zin staat in `titel` (tooltip) en in het
   *  paneel erachter. */
  let chip: string | null = null;
  let chipUitleg = "";
  if (stand.soort === "bezig") {
    chip = `Titels klaarzetten… ${Math.round(stand.percentage)} %`;
    chipUitleg = "BeatCut zet de titelmotor voor de export klaar.";
  } else if (stand.soort === "fout") {
    chip = "Titels klaarzetten mislukt";
    chipUitleg = stand.bericht;
  } else if (stand.soort === "mist") {
    chip = online ? "Titels nog niet klaar" : "Titels: internet nodig";
    chipUitleg = online
      ? "De titels in de export staan nog niet klaar. Klik om ze op te halen."
      : "Titels in de export vragen eenmalig internet.";
  }

  return {
    status,
    stand,
    chip,
    chipUitleg,
    start,
    stop,
  };
}
