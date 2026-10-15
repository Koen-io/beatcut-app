import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { relaunch } from "@tauri-apps/plugin-process";

import {
  AFTEL_MS,
  INTERVAL_MS,
  START_WACHT_MS,
  foutTekst,
  sluitVanzelf,
  toonPopup,
  type Aanleiding,
  type Controle,
  type Fase,
} from "./bijwerkstand";
import { engineBezig } from "./engine";

/** Langer dan dit is geen trage verbinding meer maar een vastgelopen controle. */
const CONTROLE_LIMIET_MS = 30_000;
/** Hoe vaak we de engine vragen of er nog werk loopt, zolang een update klaarstaat. */
const BEZIG_MS = 3000;
/** Sleutel in localStorage: wanneer er voor het laatst gekeken is. */
const SLEUTEL_LAATST = "bijwerken.laatst";

/**
 * Zelf bijwerken, in drie losse stappen die in Rust zitten (`bijwerken.rs`):
 * controleren, ophalen, installeren. De interface laat elke stap zien in de
 * pop-up (`BijwerkDialoog.tsx`) en in het instellingenpaneel.
 *
 * **Wanneer er gekeken wordt**: bij het starten (zodra de splash weg is en
 * de app staat), daarna elke `INTERVAL_MS` zolang de app open is, en op de
 * knop in de instellingen. Wat je daarvan ziet bepaalt `toonPopup()`.
 *
 * **Ophalen en installeren zijn twee aparte stappen, en dat is geen detail.**
 * Installeren sluit op Windows de app af (`std::process::exit(0)` in de
 * updater). Gebeurde dat tijdens een render, een analyse of een
 * muziekgeneratie, dan was dat werk weg. Daarom: ophalen op de achtergrond,
 * en installeren pas na een klik op "Nu herstarten" — en alleen als de
 * engine zegt dat er niets loopt.
 *
 * `online` false → er wordt niets opgehaald; een controle met de hand meldt
 * dat netjes. `actief` false → de splash staat nog, de startcontrole wacht.
 */
export function useBijwerken(online: boolean, actief: boolean) {
  const [fase, setFase] = useState<Fase>({ soort: "rust" });
  const [aanleiding, setAanleiding] = useState<Aanleiding>("start");
  const [weggeklikt, setWeggeklikt] = useState(false);
  const [laatst, setLaatst] = useState<Date | null>(() => leesLaatst());
  /** Wat de engine nu aan het doen is, of null als er niets loopt. */
  const [bezigMet, setBezigMet] = useState<string | null>(null);
  // Twee controles tegelijk hebben geen zin.
  const loopt = useRef(false);
  const gestart = useRef(false);
  const onlineRef = useRef(online);
  onlineRef.current = online;

  const controleer = useCallback(async (waarom: Aanleiding) => {
    if (loopt.current) return;
    setAanleiding(waarom);
    setWeggeklikt(false);
    if (!onlineRef.current) {
      if (waarom === "hand") {
        setFase({ soort: "fout", bericht: "Je staat op Offline. Zet Online aan om op updates te controleren." });
      }
      return;
    }
    loopt.current = true;
    setFase({ soort: "zoekt" });
    const begon = Date.now();
    try {
      // Met een tijdslimiet: een commando dat in Rust panickt geeft nooit
      // antwoord, en dan bleef de pop-up op "Controleren…" staan (15-10-2026).
      const c = await metLimiet(invoke<Controle>("bijwerken_controleer"), CONTROLE_LIMIET_MS);
      // Minstens één tel in beeld: een ring die in 80 ms al dichtvalt leest
      // als een flits, niet als een controle.
      const wacht = Math.max(0, 900 - (Date.now() - begon));
      if (wacht > 0) await new Promise((r) => setTimeout(r, wacht));
      const nu = new Date();
      setLaatst(nu);
      bewaarLaatst(nu);
      setFase(c.beschikbaar ? { soort: "nieuw", controle: c } : { soort: "bij", huidige: c.huidige });
    } catch (e) {
      console.warn("bijwerken: controle mislukt:", e);
      setFase({ soort: "fout", bericht: foutTekst(e) });
    } finally {
      loopt.current = false;
    }
  }, []);

  // Bij het starten: zodra de app staat, één keer kijken. Daarna periodiek.
  useEffect(() => {
    if (!actief || gestart.current) return;
    gestart.current = true;
    const eerste = setTimeout(() => void controleer("start"), START_WACHT_MS);
    const tik = setInterval(() => void controleer("periodiek"), INTERVAL_MS);
    return () => {
      clearTimeout(eerste);
      clearInterval(tik);
    };
  }, [actief, controleer]);

  // "Je bent bij" gaat vanzelf weg.
  useEffect(() => {
    if (!sluitVanzelf(fase) || weggeklikt) return;
    const t = setTimeout(() => setWeggeklikt(true), AFTEL_MS);
    return () => clearTimeout(t);
  }, [fase, weggeklikt]);

  const ophalen = useCallback(async () => {
    if (fase.soort !== "nieuw") return;
    const controle = fase.controle;
    setFase({ soort: "haalt", controle, ontvangen: 0, totaal: null });
    const stop = await listen<{ ontvangen: number; totaal: number | null }>("bijwerken-voortgang", (ev) => {
      setFase((f) => (f.soort === "haalt" ? { ...f, ontvangen: ev.payload.ontvangen, totaal: ev.payload.totaal } : f));
    });
    try {
      await invoke<number>("bijwerken_ophalen");
      setFase({ soort: "klaar", controle });
      setWeggeklikt(false);
    } catch (e) {
      console.warn("bijwerken: ophalen mislukt:", e);
      setFase({ soort: "fout", bericht: foutTekst(e) });
    } finally {
      stop();
    }
  }, [fase]);

  // Zolang een update klaarstaat: in de gaten houden of de engine werk heeft.
  const staatKlaar = fase.soort === "klaar";
  useEffect(() => {
    if (!staatKlaar) return;
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
  }, [staatKlaar]);

  const herstart = useCallback(async () => {
    if (fase.soort !== "klaar") return;
    // Nog één keer vragen, nu pas echt: tussen de laatste poll en deze klik
    // kan er werk gestart zijn, en installeren is op Windows onomkeerbaar.
    try {
      const uit = await engineBezig();
      if (uit.bezig) {
        setBezigMet(uit.werk[0].tekst);
        return;
      }
    } catch {
      // Engine onbereikbaar — dan loopt er ook geen render.
    }
    try {
      await invoke("bijwerken_installeer");
    } catch (e) {
      setFase({ soort: "fout", bericht: foutTekst(e) });
      return;
    }
    // Windows komt hier niet: installeren sluit de app daar zelf af.
    await relaunch();
  }, [fase]);

  return {
    fase,
    aanleiding,
    laatst,
    zichtbaar: !weggeklikt && toonPopup(aanleiding, fase),
    bezigMet,
    magHerstarten: bezigMet === null,
    controleer: () => void controleer("hand"),
    ophalen: () => void ophalen(),
    herstart: () => void herstart(),
    verberg: () => setWeggeklikt(true),
    /** De pop-up weer tonen (vanuit de instellingen) in de huidige fase. */
    toon: () => {
      setAanleiding("hand");
      setWeggeklikt(false);
    },
  };
}

export type Bijwerken = ReturnType<typeof useBijwerken>;

function leesLaatst(): Date | null {
  try {
    const s = localStorage.getItem(SLEUTEL_LAATST);
    if (s === null) return null;
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

function bewaarLaatst(d: Date): void {
  try {
    localStorage.setItem(SLEUTEL_LAATST, d.toISOString());
  } catch {
    // Geen opslag (privévenster, QA-brug): dan weet het paneel het gewoon niet.
  }
}

function metLimiet<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((los, weiger) => {
    const t = setTimeout(() => weiger(new Error("de controle duurde te lang (geen antwoord van de updater)")), ms);
    p.then((v) => { clearTimeout(t); los(v); }, (e) => { clearTimeout(t); weiger(e); });
  });
}
