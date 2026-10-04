// De live voorvertoning: speelt de montage uit edl.json echt af.
//
// Drie lagen, elk in een eigen bestand:
//   klok.ts     — de muziek is de meesterklok, het beeld volgt
//   demux.ts    — mp4box.js demuxt de proxy, WebCodecs decodeert
//   tekenen.ts  — WebGPU tekent, met de shaders uit app/shaders/ als die er zijn
//
// Hier staat alleen wat daartussen hoort: welk blok op dit moment in beeld is,
// of er een overgang loopt, en wanneer het volgende blok ingeladen moet worden.
//
// Zonder WebGPU verschijnt er geen speler maar een melding; de aanroeper toont
// dan zijn eigen stilstaande voorbeeld. Dat is bewust: PLAN-v2.md §4.4 wil geen
// `<video>`-terugval, want die geeft geen look, geen overgangen en geen
// afwerking — dan lijkt de voorvertoning iets te beloven wat de export niet doet.
import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { lookLut, type Montagestand, type Shot } from "../engine";
import { Klok } from "./klok";
import { Blokdecoder, Proxy, brontijdVan, frames } from "./demux";
import { maakDoek, type Doek, type Inpassing } from "./tekenen";
import { afwerkingUitLijst } from "./params";
import { identiteit, leesCube, type Lut } from "./lut";
import Titels from "./Titels";
import {
  kaderPas,
  kaderPuntOp,
  kaderVul,
  overgangNummer,
  vulmodusNummer,
  type Kader,
  type Stand,
} from "./uniforms";
import { duurTekst } from "../format";

/** Zoveel seconden vóór een snede wordt het volgende blok al opgezet. Het
 *  decoderen van de eerste frames kost tijd; zonder dit hapert elke snede. */
const VOORUIT = 1.0;
/** Breedte waarop de voorvertoning rekent. De proxy is 540p, dus hoger
 *  tekenen kost GPU zonder dat er detail bijkomt. */
const TEKEN_BREEDTE = 960;

/** Ken Burns: welke zoom en welke verschuiving hoort bij dit moment?
 *  `f` loopt van 0 aan het begin van het blok naar 1 aan het eind. */
function kenBurns(zoom: string, kracht: number, f: number): { zoom: number; panX: number; panY: number } {
  const k = Math.max(0, kracht);
  const t = Math.min(1, Math.max(0, f));
  switch (zoom) {
    case "in":
      return { zoom: 1 + k * t, panX: 0, panY: 0 };
    case "uit":
      return { zoom: 1 + k * (1 - t), panX: 0, panY: 0 };
    // Schuiven kan alleen als er marge is, dus zoom er eerst een beetje in.
    case "links":
      return { zoom: 1 + k, panX: 1 - 2 * t, panY: 0 };
    case "rechts":
      return { zoom: 1 + k, panX: 2 * t - 1, panY: 0 };
    case "omhoog":
      return { zoom: 1 + k, panX: 0, panY: 1 - 2 * t };
    case "omlaag":
      return { zoom: 1 + k, panX: 0, panY: 2 * t - 1 };
    default:
      return { zoom: 1, panX: 0, panY: 0 };
  }
}

/** De stukken (uitvoerduur, snelheid) van een shot. Oudere engines sturen ze
 *  niet mee; dan is het één stuk op constante snelheid, net als voorheen. */
function stukkenVan(shot: Shot): [number, number][] {
  const s = shot.snelheid_stukken;
  return s && s.length > 0 ? s : [[shot.duur, shot.snelheid]];
}

/** Alles waar de decoder van een shot op gebouwd is. Verandert hier iets —
 *  een highlight verschoven, 0,5× gekozen, opnieuw geregisseerd — dan is de
 *  bestaande decoder de verkeerde, terwijl het shot-id gelijk blijft. */
function sleutelVan(shot: Shot, proxy: string | null): string {
  return [
    proxy ?? "",
    shot.bron_in,
    shot.bron_duur,
    shot.bevriezen,
    JSON.stringify(stukkenVan(shot)),
  ].join("|");
}

type Inzet = { sleutel: string; dec: Blokdecoder | null };

type Props = {
  stand: Montagestand;
  /** Mag de speler het venster aan de spatiebalk hangen? Eén speler per scherm. */
  spatie?: boolean;
  /** Elke tekenslag, zodat de aanroeper zijn tijdlijncursor mee kan laten lopen. */
  onTijd?: (t: number) => void;
  /** Spring hiernaartoe zodra de waarde verandert — zo kan een shot aanklikken
   *  in de tijdlijn de speler meenemen. */
  zoekNaar?: number | null;
};

/** Wat de QA-brug uitleest om de framerate te meten. `window.__beatcutSpeler`. */
export type Meting = { fps: number; tijd: number; frames: number; blok: string; speelt: boolean };

/** De haken voor de gouden-frames-vergelijking (`window.__beatcutQA`).
 *
 *  Waarom dit in de speler zit en niet in een los testbestand: de vergelijking
 *  met de native compositor is alleen eerlijk als beide kanten dezelfde bytes
 *  als invoer krijgen. `bron()` geeft precies het beeld dat de keten ingaat —
 *  hetzelfde als wat `beatcut-compositor` op zijn stdin leest. Zie
 *  `ontwerp/beatcut2/qa/gouden-frames.js`. */
export type QA = {
  /** Spring naar dit moment en wacht tot er getekend is. */
  zoek(t: number, wacht?: number): Promise<void>;
  /** Het samengestelde beeld vóór de look, als RGBA8. */
  bron(): Promise<{ breedte: number; hoogte: number; data: number[] }>;
  /** Look + afwerking op een gegeven beeld, met een eigen kleurtabel. */
  keten(
    bron: number[],
    breedte: number,
    hoogte: number,
    opdracht: { cube: string | null; sterkte: number; afwerking: number[]; frame: number; seed: number },
  ): Promise<number[]>;
  /** Wat er nu in beeld is: maat, frame-index, seed, afwerking. */
  stand(): { breedte: number; hoogte: number; frame: number; seed: number; afwerking: number[]; look: string; sterkte: number; opslag: string };
  /** De brontijd die de decoder op dit moment binnen een blok zou pakken —
   *  met de speed-ramp erin. Naast `bron_in + bron_duur` van de engine te
   *  leggen zonder dat er een decoder voor nodig is. */
  brontijd(stukken: [number, number][], bronStart: number, bevriezen: number, inBlok: number): number;
  /** De decoders die nu bestaan, met de vingerafdruk waarop ze gebouwd zijn.
   *  Daarmee is te zien of een highlight- of snelheidswijziging er echt een
   *  nieuwe oplevert, en of er na opruimen niets achterblijft. */
  decoders(): { id: string; sleutel: string; geladen: boolean }[];
  /** Openstaande en in totaal gedecodeerde `VideoFrame`s (geheugenlek-check). */
  frames(): { open: number; totaal: number };
  /** De stand van de klok: speelt hij, is er muziek, waar staat hij. */
  klok(): { speelt: boolean; heeftMuziek: boolean; tijd: number };
  /** De presentatietijden van een ingelezen proxy, in decodeervolgorde.
   *  Loopt die niet op, dan bevat de proxy B-frames en bewijst dat meteen dat
   *  de lijst niet op `cts` gesorteerd is. */
  proxyvolgorde(pad: string): Promise<number[]>;
  /** De vulmodus als getal, zoals de shader hem krijgt. */
  vulmodus(modus: string): number;
  /** De overgangsoort als getal, zoals de shader hem krijgt — zodat de
   *  gouden-frames-test de lijst uit `edl.OVERGANGEN` niet hoeft te kopiëren. */
  overgangnummer(soort: string): number;
  /** Eén overgangsmoment op twee gegeven bronbeelden, met het kader op de
   *  eenheid: dezelfde stand waarin `compositor/src/overgang.rs` rekent. Zie
   *  `ontwerp/beatcut2/qa/gouden-frames-overgangen.js`. */
  overgang(
    a: number[],
    b: number[],
    breedte: number,
    hoogte: number,
    opdracht: {
      soort: number;
      meng: number;
      frame: number;
      tijd: number;
      seed: number;
      cube: string | null;
      sterkte: number;
      afwerking: number[];
      /** Optioneel: vulmodus en inpaskader per bron, voor de meting van
       *  `pas` en `wazig` tijdens een bijzondere overgang. Zonder dit staat
       *  alles op de eenheid en op "vul", net als in de export. */
      inpassing?: Inpassing;
    },
  ): Promise<number[]>;
};

export default function Speler({ stand, spatie = true, onTijd, zoekNaar }: Props) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const klok = useRef<Klok | null>(null);
  const doek = useRef<Doek | null>(null);
  /** Eén ingelezen proxy per clip-id, zodat een tweede shot uit dezelfde clip
   *  niets meer hoeft in te lezen. */
  const proxies = useRef(new Map<string, Promise<Proxy>>());
  /** Eén decoder per shot-id, voor het huidige, het vorige en het volgende blok.
   *  `sleutel` is de vingerafdruk van de configuratie waarmee hij gemaakt is;
   *  wijzigt die, dan moet de decoder weg (zie `zetKlaar`). */
  const decoders = useRef(new Map<string, Inzet>());
  /** Loopnummer van deze spelerssessie. Elke laadopdracht onthoudt het nummer
   *  dat gold toen hij begon en doet niets meer als het inmiddels verhoogd is
   *  — anders maakt een trage `Proxy.lees()` na het opruimen alsnog een
   *  decoder aan, en die wordt dan door niemand meer gesloten. */
  const sessie = useRef(0);
  /** De kleurtabel van de gekozen look. Komt over de RPC en kan later
   *  aankomen dan het doek; daarom in een ref en niet in de state. */
  const lut = useRef<Lut>(identiteit());
  /** De klok, voor de titellaag. Een ref: die loopt op zijn eigen tekenlus en
   *  hoeft de speler niet elke frame opnieuw te laten renderen. */
  const tijdRef = useRef(0);
  const [speelt, setSpeelt] = useState(false);
  const [tijd, setTijd] = useState(0);
  const [fout, setFout] = useState<string | null>(null);
  const [fps, setFps] = useState(0);
  const [herkomst, setHerkomst] = useState("");

  const shots = stand.shots;
  const duur = stand.duur;
  const [canvasB, canvasH] = stand.vorm.split(":").map(Number);
  const canvasVerhouding = canvasB && canvasH ? canvasB / canvasH : 16 / 9;

  const proxypad = useCallback(
    (shot: Shot): string | null => shot.proxy ?? stand.clips[shot.clip]?.proxy ?? null,
    [stand.clips],
  );

  const proxyVoor = useCallback(
    (pad: string): Promise<Proxy> => {
      const bestaand = proxies.current.get(pad);
      if (bestaand) return bestaand;
      const nieuw = Proxy.lees(pad);
      proxies.current.set(pad, nieuw);
      return nieuw;
    },
    [],
  );

  /** Zet een decoder klaar voor dit shot, als die er nog niet is — of als de
   *  decoder die er staat op een andere configuratie gebouwd is. */
  const zetKlaar = useCallback(
    (shot: Shot | undefined) => {
      if (!shot) return;
      const pad = proxypad(shot);
      if (!pad) return;
      const sleutel = sleutelVan(shot, pad);
      const staand = decoders.current.get(shot.id);
      if (staand && staand.sleutel === sleutel) return;
      // Een decoder op een achterhaalde configuratie moet eerst dicht; anders
      // blijven zijn frames en zijn GPU-geheugen hangen.
      staand?.dec?.sluit();
      // De plek bezetten met `dec: null` houdt een tweede aanroep tegen
      // terwijl de eerste nog laadt.
      decoders.current.set(shot.id, { sleutel, dec: null });
      const mijn = sessie.current;
      void proxyVoor(pad)
        .then((pr) => {
          // Opgeruimd of al weer vervangen terwijl we laadden? Dan hoort hier
          // niets meer te komen.
          if (mijn !== sessie.current) return;
          if (decoders.current.get(shot.id)?.sleutel !== sleutel) return;
          decoders.current.set(shot.id, {
            sleutel,
            dec: new Blokdecoder(pr, shot.bron_in, stukkenVan(shot), shot.bevriezen),
          });
        })
        .catch((e) => {
          if (mijn !== sessie.current) return;
          if (decoders.current.get(shot.id)?.sleutel === sleutel) {
            decoders.current.delete(shot.id);
          }
          setFout(String(e));
        });
    },
    [proxyVoor, proxypad],
  );

  // -- opzetten en opruimen ------------------------------------------------
  useEffect(() => {
    let weg = false;
    const k = new Klok();
    klok.current = k;
    if (stand.muziek.pad) void k.laad(stand.muziek.pad, stand.muziek.bron_start);
    const c = canvas.current;
    if (c) {
      void maakDoek(c)
        .then((d) => {
          if (weg) return d.sluit();
          d.formaat(TEKEN_BREEDTE, Math.round(TEKEN_BREEDTE / canvasVerhouding));
          d.zetLut(lut.current);
          doek.current = d;
          setHerkomst(`${d.herkomst} · ${d.opslag}`);
        })
        .catch((e) => setFout(String(e)));
    }
    return () => {
      weg = true;
      // Eerst het loopnummer, dan opruimen: alles wat nu nog aan het laden is
      // ziet daarna dat het niet meer hoeft.
      sessie.current++;
      for (const d of decoders.current.values()) d.dec?.sluit();
      decoders.current.clear();
      proxies.current.clear();
      doek.current?.sluit();
      doek.current = null;
      k.sluit();
      klok.current = null;
    };
    // Eén keer per montage: een nieuwe montage betekent nieuwe proxies.
  }, [stand.project, stand.muziek.pad, canvasVerhouding]);

  // -- de kleurtabel van de look -------------------------------------------
  // Over de RPC, want `looks/` ligt buiten de projectmap en het asset-protocol
  // van Tauri komt daar niet (zie `rpc.py` → `look.lut`).
  useEffect(() => {
    let geldig = true;
    const zet = (l: Lut) => {
      if (!geldig) return;
      lut.current = l;
      doek.current?.zetLut(l);
    };
    lookLut(stand.look?.id ?? "geen")
      .then(({ cube }) => zet(cube ? leesCube(cube) : identiteit()))
      // Geen tabel is geen fout: dan ligt er geen look over het beeld, en dat
      // is beter dan een speler die helemaal niets toont.
      .catch(() => zet(identiteit()));
    return () => {
      geldig = false;
    };
  }, [stand.look?.id]);

  // -- de tekenlus ---------------------------------------------------------
  useEffect(() => {
    let draait = true;
    let handvat = 0;
    let getekend = 0;
    let gemeten = performance.now();

    const lus = () => {
      if (!draait) return;
      handvat = requestAnimationFrame(lus);
      const k = klok.current;
      const d = doek.current;
      if (!k || !d) return;

      let t = k.tijd();
      if (t >= duur) {
        k.pauzeer();
        k.zoek(duur);
        t = duur;
        setSpeelt(false);
      }

      // Welk blok staat er nu? De blokken sluiten op elkaar aan, dus de laatste
      // die begonnen is, is de goede.
      let i = 0;
      for (let n = 0; n < shots.length; n++) if (shots[n].start <= t) i = n;
      const nu = shots[i];
      if (!nu) return;

      // Loopt er een overgang? Die zit aan het begín van het blok: het vorige
      // blok loopt nog even door terwijl dit al binnenkomt.
      const over = nu.overgang_duur ?? 0;
      const vorige = i > 0 ? shots[i - 1] : undefined;
      const bezig = over > 0 && vorige && t < nu.start + over;
      const meng = bezig ? Math.min(1, Math.max(0, (t - nu.start) / over)) : 1;

      zetKlaar(nu);
      zetKlaar(shots[i + 1]);
      if (bezig) zetKlaar(vorige);
      // Het volgende blok vroeg genoeg opzetten, anders hapert de snede.
      if (t > nu.start + nu.duur - VOORUIT) zetKlaar(shots[i + 1]);

      const decA = (bezig && vorige ? decoders.current.get(vorige.id) : decoders.current.get(nu.id))?.dec;
      const decB = bezig ? decoders.current.get(nu.id)?.dec : null;
      const shotA = bezig && vorige ? vorige : nu;
      const frameA = decA?.pak(t - shotA.start) ?? null;
      const frameB = bezig ? (decB?.pak(t - nu.start) ?? null) : null;

      const kaderVoor = (s: Shot, frame: VideoFrame | null): { vul: Kader; pas: Kader } => {
        const b = frame?.displayWidth || frame?.codedWidth || 16;
        const h = frame?.displayHeight || frame?.codedHeight || 9;
        const f = (t - s.start) / Math.max(0.001, s.duur);
        const kb = kenBurns(s.zoom, s.zoom_kracht ?? 0, f);
        const [kx, ky] = kaderPuntOp(s.kader, f);
        return {
          vul: kaderVul(b / h, canvasVerhouding, kb.zoom, kb.panX, kb.panY, kx, ky),
          pas: kaderPas(b / h, canvasVerhouding),
        };
      };
      const ka = kaderVoor(shotA, frameA);
      const kbk = kaderVoor(nu, frameB ?? frameA);

      const uit: Stand = {
        kaderA: ka.vul,
        kaderB: kbk.vul,
        pasA: ka.pas,
        pasB: kbk.pas,
        meng: bezig ? meng : 1,
        overgang: bezig ? overgangNummer(nu.overgang) : 0,
        vulmodusA: vulmodusNummer(shotA.vulmodus ?? "vul"),
        vulmodusB: vulmodusNummer(nu.vulmodus ?? "vul"),
        tijd: t,
        frame: Math.round(t * stand.fps),
        seed: stand.effectseed ?? 0,
        canvasVerhouding,
        looksterkte: stand.look?.sterkte ?? 1,
        afwerking: [
          stand.afwerking?.korrel ?? 0,
          stand.afwerking?.halation ?? 0,
          stand.afwerking?.gloed ?? 0,
          stand.afwerking?.vignet ?? 0,
          stand.afwerking?.lichtlek ?? 0,
          stand.afwerking?.breedbeeld ?? 0,
          stand.afwerking?.filmtrilling ?? 0,
          stand.afwerking?.kleurrand ?? 0,
        ],
      };
      // Tijdens een overgang hoort het inkomende beeld in slot B; staat er nog
      // niets, dan houdt A het beeld vast in plaats van zwart te worden.
      d.teken(frameA, frameB, uit);

      // Decoders van blokken die voorbij zijn mogen weg; elk frame dat open
      // blijft staan houdt GPU-geheugen vast.
      for (const [id, inzet] of decoders.current) {
        const n = shots.findIndex((s) => s.id === id);
        if (n >= 0 && n < i - 1) {
          inzet.dec?.sluit();
          decoders.current.delete(id);
        }
      }

      // Een decoder die omvalt (een codec die deze webview niet kan) moet in
      // beeld komen in plaats van stil een bevroren frame te laten staan.
      const kapot = decA?.fout ?? decB?.fout;
      if (kapot) setFout(`voorvertoning niet mogelijk voor deze proxy — ${kapot}`);

      getekend++;
      const nuMs = performance.now();
      if (nuMs - gemeten >= 500) {
        const gemetenFps = (getekend * 1000) / (nuMs - gemeten);
        setFps(Math.round(gemetenFps));
        getekend = 0;
        gemeten = nuMs;
        (window as unknown as { __beatcutSpeler?: Meting }).__beatcutSpeler = {
          fps: Math.round(gemetenFps),
          tijd: t,
          frames: Math.round(t * stand.fps),
          blok: nu.id,
          speelt: k.speelt,
        };
      }
      tijdRef.current = t;
      setTijd(t);
      onTijd?.(t);
    };
    handvat = requestAnimationFrame(lus);
    return () => {
      draait = false;
      cancelAnimationFrame(handvat);
    };
  }, [shots, duur, canvasVerhouding, stand.fps, stand.effectseed, zetKlaar, onTijd]);

  const zoek = useCallback(
    (t: number) => {
      const k = klok.current;
      if (!k) return;
      k.zoek(Math.min(duur, Math.max(0, t)));
      // Alle decoders weg: na een sprong staan hun buffers op het verkeerde
      // moment, en een decoder terugspoelen kost net zoveel als een nieuwe.
      // Het loopnummer erbij op, zodat een laadopdracht die nog loopt geen
      // decoder meer aanmaakt voor het moment van vóór de sprong.
      sessie.current++;
      for (const [id, inzet] of decoders.current) {
        inzet.dec?.sluit();
        decoders.current.delete(id);
      }
      setTijd(k.tijd());
    },
    [duur],
  );

  const speelPauze = useCallback(() => {
    const k = klok.current;
    if (!k) return;
    if (k.speelt) {
      k.pauzeer();
      setSpeelt(false);
    } else {
      // Aan het eind blijven staan en dan weer op ▶: de klok springt naar nul,
      // maar de decoders staan nog op het eindframe en kunnen niet
      // terugspoelen. Dezelfde reset als bij een sprong, en daarna starten.
      if (k.tijd() >= duur) {
        zoek(0);
        k.start(0);
      } else {
        k.start(k.tijd());
      }
      setSpeelt(true);
    }
  }, [duur, zoek]);

  useEffect(() => {
    if (zoekNaar === null || zoekNaar === undefined) return;
    zoek(zoekNaar);
  }, [zoekNaar, zoek]);

  // -- de haken voor de gouden-frames-vergelijking -------------------------
  // Alleen lezen en rekenen; de speler zelf verandert er niet van. Zie
  // `ontwerp/beatcut2/qa/gouden-frames.js` voor wie ze aanroept.
  useEffect(() => {
    const wachtFrames = (n: number) =>
      new Promise<void>((klaar) => {
        let over = n;
        const stap = () => (over-- <= 0 ? klaar() : requestAnimationFrame(stap));
        requestAnimationFrame(stap);
      });
    const haken: QA = {
      async zoek(t, wacht = 90) {
        zoek(t);
        // Na een sprong zijn alle decoders weg en moeten de eerste frames
        // opnieuw gedecodeerd worden; vandaar ruim wachten in plaats van één
        // tekenslag.
        await wachtFrames(wacht);
      },
      async bron() {
        const d = doek.current;
        if (!d) throw new Error("geen doek");
        const data = await d.grijpBron();
        return { breedte: canvas.current!.width, hoogte: canvas.current!.height, data: Array.from(data) };
      },
      async keten(bron, breedte, hoogte, opdracht) {
        const d = doek.current;
        if (!d) throw new Error("geen doek");
        d.zetLut(opdracht.cube ? leesCube(opdracht.cube) : identiteit());
        try {
          const uit = await d.ketenOp(new Uint8Array(bron), breedte, hoogte, {
            frame: opdracht.frame,
            seed: opdracht.seed,
            sterkte: opdracht.sterkte,
            afwerking: afwerkingUitLijst(opdracht.afwerking),
          });
          return Array.from(uit);
        } finally {
          // De montage heeft zijn eigen look; die moet erna weer staan.
          d.zetLut(lut.current);
        }
      },
      async overgang(a, b, breedte, hoogte, opdracht) {
        const d = doek.current;
        if (!d) throw new Error("geen doek");
        d.zetLut(opdracht.cube ? leesCube(opdracht.cube) : identiteit());
        try {
          const uit = await d.overgangOp(
            new Uint8Array(a),
            new Uint8Array(b),
            breedte,
            hoogte,
            { soort: opdracht.soort, meng: opdracht.meng, frame: opdracht.frame, tijd: opdracht.tijd, seed: opdracht.seed },
            {
              frame: opdracht.frame,
              seed: opdracht.seed,
              sterkte: opdracht.sterkte,
              afwerking: afwerkingUitLijst(opdracht.afwerking),
            },
            opdracht.inpassing,
          );
          return Array.from(uit);
        } finally {
          d.zetLut(lut.current);
        }
      },
      brontijd(stukken, bronStart, bevriezen, inBlok) {
        return brontijdVan(stukken, bronStart, bevriezen, inBlok);
      },
      decoders() {
        return [...decoders.current].map(([id, inzet]) => ({
          id,
          sleutel: inzet.sleutel,
          geladen: inzet.dec !== null,
        }));
      },
      frames() {
        return { ...frames };
      },
      klok() {
        const k = klok.current;
        return { speelt: k?.speelt ?? false, heeftMuziek: k?.heeftMuziek ?? false, tijd: k?.tijd() ?? 0 };
      },
      async proxyvolgorde(pad) {
        const pr = await Proxy.lees(pad);
        return pr.samples.map((s) => s.cts / s.timescale);
      },
      vulmodus(modus) {
        return vulmodusNummer(modus);
      },
      overgangnummer(soort) {
        return overgangNummer(soort);
      },
      stand() {
        const t = klok.current?.tijd() ?? 0;
        const a = stand.afwerking;
        return {
          breedte: canvas.current?.width ?? 0,
          hoogte: canvas.current?.height ?? 0,
          frame: Math.round(t * stand.fps),
          seed: stand.effectseed ?? 0,
          afwerking: [a?.korrel ?? 0, a?.halation ?? 0, a?.gloed ?? 0, a?.vignet ?? 0,
                      a?.lichtlek ?? 0, a?.breedbeeld ?? 0, a?.filmtrilling ?? 0, a?.kleurrand ?? 0],
          look: stand.look?.id ?? "geen",
          sterkte: stand.look?.sterkte ?? 1,
          opslag: doek.current?.opslag ?? "",
        };
      },
    };
    (window as unknown as { __beatcutQA?: QA }).__beatcutQA = haken;
    return () => {
      delete (window as unknown as { __beatcutQA?: QA }).__beatcutQA;
    };
  }, [zoek, stand]);

  // De spatiebalk, zoals elke speler. Niet als de gebruiker in een veld typt.
  useEffect(() => {
    if (!spatie) return;
    const op = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const doel = e.target as HTMLElement | null;
      if (doel && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(doel.tagName)) return;
      e.preventDefault();
      speelPauze();
    };
    window.addEventListener("keydown", op);
    return () => window.removeEventListener("keydown", op);
  }, [spatie, speelPauze]);


  if (fout) {
    // Het stilstaande voorbeeld: het shotbeeldje van het eerste blok. Beter dan
    // een leeg vak, en het is hetzelfde beeldje dat de tijdlijn al toont.
    const voorbeeld = shots.find((s) => s.thumbnail)?.thumbnail ?? null;
    return (
      <div className="speler-doek">
        <div className="speler geen-proxy">
          {voorbeeld !== null && (
            <img className="geen-proxy-beeld" src={convertFileSrc(voorbeeld)} alt="" />
          )}
          <strong>Geen live voorvertoning.</strong>
          <span className="noot">{fout}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="speler-doek">
      <div className="speler-beeld">
        <canvas
          ref={canvas}
          className="speler speler-canvas"
          style={{ aspectRatio: `${canvasB || 16} / ${canvasH || 9}` }}
          data-fps={fps}
        />
        {/* `revisie`: opnieuw regisseren houdt hetzelfde project en dezelfde
            speler, maar schrijft een nieuwe EDL. Zonder deze sleutel bleef de
            oude titel boven de nieuwe beelden staan. */}
        <Titels
          project={stand.project}
          revisie={JSON.stringify(stand.titels)}
          tijd={tijdRef}
          beeld={canvas}
        />
      </div>
      <div className="speler-balk">
        <button className="speelknop" onClick={speelPauze} aria-label={speelt ? "Pauzeren" : "Afspelen"}>
          {speelt ? "❚❚" : "▶"}
        </button>
        <div
          className="scrub"
          onPointerDown={(e) => {
            const vak = e.currentTarget.getBoundingClientRect();
            zoek(((e.clientX - vak.left) / vak.width) * duur);
          }}
        >
          <div className="scrub-spoor" />
          <div className="scrub-tot" style={{ width: `${duur > 0 ? (tijd / duur) * 100 : 0}%` }} />
          {shots.slice(1).map((s) => (
            <span
              key={s.id}
              className="scrub-snede"
              style={{ left: `${(s.start / Math.max(0.001, duur)) * 100}%` }}
              title={`${s.nr}. ${s.overgang}`}
            />
          ))}
          <div className="scrub-knop" style={{ left: `${duur > 0 ? (tijd / duur) * 100 : 0}%` }} />
        </div>
        <span className="mono">
          {duurTekst(tijd)} / {duurTekst(duur)}
        </span>
        <span className="noot" title={`look-shader: ${herkomst}`}>
          {fps} fps
        </span>
      </div>
    </div>
  );
}
