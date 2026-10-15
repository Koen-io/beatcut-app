// Stap 1 — Media: projecten kiezen, clips erin slepen, laten verwerken,
// en per clip aan/uit zetten. Ontwerp: ontwerp/beatcut2/Main.dc.html.
//
// Alles wat de engine weet komt uit engine.ts; dit bestand houdt geen eigen
// administratie bij behalve wat de interface nodig heeft om te tekenen.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import { duurTekst } from "./format";
import { balkDeel, tijdenTekst } from "./voortgang";
import {
  GEBEURTENIS,
  VIDEO_EXTENSIES,
  clipZet,
  projectClips,
  projectMaak,
  projectVerwerk,
  projectVoegToe,
  projectZonderOntbrekend,
  projecten,
  type Clip,
  type EngineGebeurtenis,
  type Project,
  type Verwijderd,
  type Voortgang,
} from "./engine";
import Zijbalk from "./Zijbalk";
import VerwijderDialoog from "./VerwijderDialoog";
import TerugzetDialoog from "./TerugzetDialoog";
import { grootteTekst, kruimelpad } from "./verwijderkeuze";
import { teruggezetTekst, wachtTekst, type Teruggezet } from "./terugzetkeuze";
import { EDITIE } from "./editie";

/** Het open project, alleen voor deze keer dat de app draait. Bewust
 *  sessionStorage: wisselen tussen de stappen houdt het project vast, maar een
 *  nieuwe start begint leeg — Koen wil bij het openen niet in het vorige
 *  project belanden (04-10-2026). Kies er een in de lijst, of sleep video's
 *  erin en er komt meteen een nieuw project. */
const ONTHOUD = "beatcut.project";
/** Vanaf deze score krijgt een clip de accentkleur — zie het ontwerp. */
const GOED = 0.8;
const SKELETONS = 12;
/** Hoe lang "staat in de Prullenmand" blijft staan. Lang genoeg om te lezen
 *  waar het bewaarde heen ging, kort genoeg om niet te blijven hangen. */
const MELDING_MS = 9000;

const STAP_TEKST: Record<Voortgang["stap"], string> = {
  inlezen: "Beelden inlezen",
  analyseren: "Analyseren",
};

function scoreTekst(score: number | null): string {
  return score === null ? "—" : score.toFixed(2).replace(".", ",");
}

/** Laat de klok lopen zolang er werk is, zodat "verstreken" elke seconde
 *  opschuift. De engine meldt alleen bij een afgeronde clip, en dat kan bij een
 *  lange 4K-opname een halve minuut duren — een teller die dan stilstaat leest
 *  als vastgelopen. */
function useSeconde(actief: boolean): number {
  const [tik, setTik] = useState(0);
  useEffect(() => {
    if (!actief) return;
    const id = setInterval(() => setTik((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [actief]);
  return tik;
}

type Props = {
  naarStijl: () => void;
  /** De titelbalk toont de projectnaam; die woont hier, niet in App. */
  onProject: (naam: string | null) => void;
};

export default function Media({ naarStijl, onProject }: Props) {
  const [lijst, setLijst] = useState<Project[] | null>(null);
  const [gekozen, setGekozen] = useState<string | null>(() => sessionStorage.getItem(ONTHOUD));
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [voortgang, setVoortgang] = useState<Voortgang | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [sleept, setSleept] = useState(false);
  const [nieuw, setNieuw] = useState("");
  const [bezigToevoegen, setBezigToevoegen] = useState(false);
  /** Het "…"-menu van één project, op de plek waar erom gevraagd werd. */
  const [menu, setMenu] = useState<{ naam: string; x: number; y: number } | null>(null);
  const [teVerwijderen, setTeVerwijderen] = useState<string | null>(null);
  const [verwijderd, setVerwijderd] = useState<Verwijderd | null>(null);
  /** Het pad van de kopie-zip waarvoor de terugzetdialoog open staat. */
  const [terugTeZetten, setTerugTeZetten] = useState<string | null>(null);
  const [teruggezet, setTeruggezet] = useState<Teruggezet | null>(null);

  // De gebeurtenislistener hangt er één keer, maar moet wel weten welk
  // project nú open staat; een ref voorkomt dat hij telkens opnieuw hangt.
  const gekozenRef = useRef(gekozen);
  gekozenRef.current = gekozen;
  /** Wanneer de laatste voortgangsmelding binnenkwam, als Date.now(). De
   *  tijden in die melding staan stil tot de volgende; hiermee loopt de teller
   *  tussendoor door. */
  const ontvangen = useRef(0);

  const huidige = lijst?.find((p) => p.naam === gekozen) ?? null;

  const haalLijst = useCallback(async () => {
    const p = await projecten();
    setLijst(p);
    return p;
  }, []);

  // Een traag antwoord voor project A mag het raster van B niet overschrijven:
  // klikken op een kaart zou dan de bestandsnaam uit A naar B sturen.
  const haalClips = useCallback(async (naam: string) => {
    try {
      const nieuw = await projectClips(naam);
      if (gekozenRef.current === naam) setClips(nieuw);
    } catch (e) {
      if (gekozenRef.current !== naam) return;
      setFout(String(e));
      setClips([]);
    }
  }, []);

  // Eerste lading: lijst ophalen en het onthouden project terugvinden.
  useEffect(() => {
    (async () => {
      try {
        const p = await haalLijst();
        const onthouden = sessionStorage.getItem(ONTHOUD);
        setGekozen(p.some((q) => q.naam === onthouden) ? onthouden : null);
      } catch (e) {
        setFout(String(e));
        setLijst([]);
      }
    })();
  }, [haalLijst]);

  useEffect(() => {
    onProject(gekozen);
    if (gekozen === null) {
      setClips([]);
      return;
    }
    sessionStorage.setItem(ONTHOUD, gekozen);
    setClips(null);
    setVoortgang(null);
    setFout(null);
    void haalClips(gekozen);
  }, [gekozen, haalClips, onProject]);

  // Voortgang, klaar en fout van de engine. Alleen het open project telt:
  // een andere kiezen tijdens het verwerken mag de balk niet laten springen.
  useEffect(() => {
    const stop = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.project !== gekozenRef.current) return;
      // Alleen het inlezen hoort op dit scherm. Een render of muziekgeneratie
      // voor hetzelfde project stuurde hier anders de analysebalk aan, en zijn
      // "klaar" wiste de voortgang van het inlezen.
      if (payload.data.werk !== "verwerk") return;
      if (payload.gebeurtenis === "voortgang") {
        ontvangen.current = Date.now();
        setVoortgang(payload.data);
        return;
      }
      setVoortgang(null);
      if (payload.gebeurtenis === "fout") {
        setFout(payload.data.fout);
        return;
      }
      setFout(null);
      void haalLijst();
      void haalClips(payload.data.project);
    });
    return () => {
      void stop.then((f) => f());
    };
  }, [haalClips, haalLijst]);

  const voegToe = useCallback(
    async (paden: string[]) => {
      if (paden.length === 0) return;
      setBezigToevoegen(true);
      setFout(null);
      try {
        // Zonder project geen stille no-op meer: maak er meteen een, met een
        // naam die je later kunt herkennen. Zo werkt de allereerste sleep.
        let doel = gekozen;
        if (doel === null) {
          doel = (await projectMaak(vrijeNaam(lijst))).naam;
          setGekozen(doel);
          gekozenRef.current = doel;
        }
        const toe = await projectVoegToe(doel, paden);
        // Stil overslaan is hoe iemand denkt dat hij veertig clips importeerde.
        const mis = toe.bestanden.filter((b) => b.fout !== undefined);
        if (mis.length > 0) {
          setFout(mis.map((b) => `${b.naam}: ${b.fout}`).join("\n"));
        }
        await haalClips(doel);
        await haalLijst();
        // Liep er al een ronde, dan boekt de engine er zelf één achteraan
        // (`ingepland`) — die ronde pakt deze clips op. Dat hoort daar en niet
        // hier: alleen de engine weet wanneer een ronde afloopt, en alleen zo
        // kan de tijdschatting de bijgeboekte clips meerekenen in plaats van
        // halverwege opnieuw te beginnen.
        const start = await projectVerwerk(doel);
        // Alleen als dit project nog open staat: anders kreeg het project
        // waar je intussen naartoe ging een balk die nooit meer wegging.
        if (start.gestart && gekozenRef.current === doel) {
          // De eerste voortgangsmelding kan even op zich laten wachten. Zonder
          // dit valt de onderbalk terug op "klaar" en flikkert de knop aan.
          ontvangen.current = Date.now();
          setVoortgang({ werk: "verwerk", project: doel, stap: "inlezen", gedaan: 0, totaal: 0, tekst: "Starten…" });
        }
      } catch (e) {
        setFout(String(e));
      } finally {
        setBezigToevoegen(false);
      }
    },
    [gekozen, lijst, haalClips, haalLijst],
  );

  // Tauri handelt slepen zelf af; HTML5-dropevents komen niet aan.
  useEffect(() => {
    const stop = getCurrentWebview().onDragDropEvent(({ payload }) => {
      if (payload.type === "over") {
        setSleept(true);
      } else if (payload.type === "drop") {
        setSleept(false);
        void voegToe(payload.paths);
      } else {
        setSleept(false);
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, [voegToe]);

  async function kiesBestanden() {
    const keuze = await open({
      multiple: true,
      directory: false,
      filters: [{ name: "Video", extensions: VIDEO_EXTENSIES }],
    });
    if (keuze) await voegToe(keuze);
  }

  // Het menu sluit bij een klik ernaast, bij Esc en als het venster schuift.
  useEffect(() => {
    if (menu === null) return;
    const sluit = () => setMenu(null);
    const toets = (e: KeyboardEvent) => e.key === "Escape" && sluit();
    window.addEventListener("pointerdown", sluit);
    window.addEventListener("resize", sluit);
    window.addEventListener("keydown", toets);
    return () => {
      window.removeEventListener("pointerdown", sluit);
      window.removeEventListener("resize", sluit);
      window.removeEventListener("keydown", toets);
    };
  }, [menu]);

  useEffect(() => {
    if (verwijderd === null) return;
    const id = setTimeout(() => setVerwijderd(null), MELDING_MS);
    return () => clearTimeout(id);
  }, [verwijderd]);

  useEffect(() => {
    if (teruggezet === null) return;
    const id = setTimeout(() => setTeruggezet(null), MELDING_MS);
    return () => clearTimeout(id);
  }, [teruggezet]);

  async function kiesKopie() {
    const keuze = await open({
      title: "Kopie van een project kiezen",
      multiple: false,
      directory: false,
      filters: [{ name: `${EDITIE.naam}-kopie`, extensions: ["zip"] }],
    });
    if (typeof keuze === "string") setTerugTeZetten(keuze);
  }

  /** Het project staat er weer: open het, en laat de voorvertoningen opnieuw
   *  maken als die niet in de kopie zaten. */
  async function naTerugzetten(uit: Teruggezet) {
    setTerugTeZetten(null);
    setVerwijderd(null);
    setTeruggezet(uit);
    setFout(null);
    setGekozen(uit.naam);
    gekozenRef.current = uit.naam;
    await haalLijst();
    if (uit.verwerken) await startVerwerk(uit.naam);
  }

  async function startVerwerk(naam: string) {
    try {
      const start = await projectVerwerk(naam);
      if (start.gestart && gekozenRef.current === naam) {
        ontvangen.current = Date.now();
        setVoortgang({ werk: "verwerk", project: naam, stap: "inlezen", gedaan: 0, totaal: 0, tekst: "Starten…" });
      }
    } catch (e) {
      setFout(String(e));
    }
  }

  /** De gebruiker heeft de ontbrekende video's niet meer: het project gaat
   *  verder met wat er ligt, en wordt daarvoor opnieuw ingelezen. */
  async function verderZonder(naam: string) {
    try {
      await projectZonderOntbrekend(naam);
      await haalLijst();
      await haalClips(naam);
      await startVerwerk(naam);
    } catch (e) {
      setFout(String(e));
    }
  }

  /** Was het het open project, dan terug naar de lege startstand — en dat
   *  vóór de engine begint, zodat niets in beeld nog een bestand vasthoudt. */
  function sluitAls(naam: string) {
    if (gekozenRef.current !== naam) return;
    sessionStorage.removeItem(ONTHOUD);
    gekozenRef.current = null;
    setGekozen(null);
  }

  async function maakProject(naam: string) {
    const schoon = naam.trim();
    if (schoon === "") return;
    setFout(null);
    try {
      const status = await projectMaak(schoon);
      setNieuw("");
      await haalLijst();
      setGekozen(status.naam);
    } catch (e) {
      setFout(String(e));
    }
  }

  // Optimistisch: de kaart reageert meteen, en draait terug als de engine
  // het niet accepteert. Een vinkje dat een halve seconde nadenkt voelt stuk.
  async function zet(clip: Clip) {
    if (gekozen === null) return;
    const aan = !clip.aan;
    setClips((c) => c?.map((q) => (q.naam === clip.naam ? { ...q, aan } : q)) ?? null);
    try {
      await clipZet(gekozen, clip.naam, aan);
    } catch (e) {
      setFout(String(e));
      setClips((c) => c?.map((q) => (q.naam === clip.naam ? { ...q, aan: clip.aan } : q)) ?? null);
    }
  }

  const aantalAan = clips?.filter((c) => c.aan).length ?? 0;
  const bezig = voortgang !== null || bezigToevoegen;
  const analyseKlaar = huidige?.is_geanalyseerd === true && !bezig;
  const wacht = huidige !== null && huidige.ontbreekt.length > 0 ? wachtTekst(huidige.ontbreekt) : null;
  const kanDoor = analyseKlaar && aantalAan > 0;

  // Elke seconde opnieuw tekenen zolang er werk is; `sinds` vult het gat
  // tussen twee meldingen van de engine.
  useSeconde(bezig);
  const sinds = voortgang === null ? 0 : Math.max(0, (Date.now() - ontvangen.current) / 1000);
  const verstreken = voortgang?.verstreken === undefined ? null : voortgang.verstreken + sinds;
  // `resterend: null` betekent iets anders dan `undefined`: de engine meet nog
  // en weet het niet (→ "schatten…"), tegenover werk dat helemaal niet schat.
  const schat = voortgang !== null && "resterend" in voortgang;
  const resterend =
    voortgang?.resterend == null ? null : Math.max(0, voortgang.resterend - sinds);
  // De balk mag nooit terug — dat leest als een fout. De engine klinkt zijn
  // eigen breuk al vast, maar de seconden die hier tussen twee meldingen
  // bijgeteld worden vallen weg zodra de volgende melding binnenkomt, en dan
  // zakt de balk een procent terug. Een maximum eroverheen is genoeg; bij een
  // nieuwe klus (geen voortgang meer) begint hij gewoon opnieuw.
  const hoogste = useRef(0);
  if (voortgang === null) hoogste.current = 0;
  const ruw = balkDeel(voortgang, sinds);
  const deel = ruw === null ? null : (hoogste.current = Math.max(hoogste.current, ruw));
  const tijden = tijdenTekst(verstreken, schat, resterend);

  return (
    <div className={`werkvlak${sleept ? " sleept" : ""}`}>
      <Zijbalk
        kant="links"
        sleutel="media"
        standaard={232}
        naam="de projectlijst"
      >
        <div className="groep">
          <div className="kop-klein">Projecten</div>
          {lijst === null && <div className="lijst-leeg">Laden…</div>}
          {lijst?.length === 0 && <div className="lijst-leeg">Nog geen projecten</div>}
          {lijst?.map((p) => (
            <div
              key={p.naam}
              className="lijst-rij"
              onContextMenu={(e) => {
                e.preventDefault();
                setMenu({ naam: p.naam, x: e.clientX, y: e.clientY });
              }}
            >
              <button
                className="lijst-item"
                aria-pressed={p.naam === gekozen}
                onClick={() => setGekozen(p.naam)}
              >
                <span className="naam">{p.naam}</span>
                <span className="mono aantal">{p.aantal_clips}</span>
              </button>
              <button
                className="lijst-meer"
                aria-label={`Meer voor ${p.naam}`}
                aria-haspopup="menu"
                aria-expanded={menu?.naam === p.naam}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  const vak = e.currentTarget.getBoundingClientRect();
                  setMenu(menu?.naam === p.naam ? null : { naam: p.naam, x: vak.left, y: vak.bottom + 4 });
                }}
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                  <circle cx="2.5" cy="7" r="1.3" />
                  <circle cx="7" cy="7" r="1.3" />
                  <circle cx="11.5" cy="7" r="1.3" />
                </svg>
              </button>
            </div>
          ))}
          <input
            className="nieuw-project"
            value={nieuw}
            placeholder="+ Nieuw project"
            aria-label="Naam van een nieuw project"
            onChange={(e) => setNieuw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void maakProject(nieuw);
              if (e.key === "Escape") setNieuw("");
            }}
          />
          <button className="lijst-actie" onClick={() => void kiesKopie()}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 7a5 5 0 1 0 1.6-3.7" />
              <path d="M2 1.8v2.4h2.4" />
            </svg>
            Kopie terugzetten…
          </button>
        </div>

        {teruggezet !== null && (
          <div className="melding-weg" role="status">
            <b>"{teruggezet.naam}" is teruggezet</b>
            {teruggezetTekst(teruggezet) !== "" && <span>{teruggezetTekst(teruggezet)}</span>}
          </div>
        )}

        {verwijderd !== null && (
          <div className="melding-weg" role="status">
            <b>"{verwijderd.naam}" staat in de {verwijderd.prullenbak}</b>
            <span>
              {grootteTekst(verwijderd.vrijgemaakt)} opgeruimd.
              {verwijderd.bewaard !== null && <> Bewaard in {kruimelpad(verwijderd.bewaard)}.</>}
              {verwijderd.kopie !== null && <> Kopie: {kruimelpad(verwijderd.kopie, 2)}.</>}
            </span>
          </div>
        )}

        <div className="voetnoot">
          <b>Lokaal</b>
          <span>
            Proxies, analyse en montage blijven op deze computer. Bronbestanden worden nooit
            aangeraakt.
          </span>
        </div>
      </Zijbalk>

      {menu !== null && (
        <div
          className="rijmenu"
          role="menu"
          aria-label={`Project ${menu.naam}`}
          style={{ left: menu.x, top: menu.y }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {/* Hier komt later Hernoemen bij; het menu is er al op gebouwd. */}
          <button
            role="menuitem"
            className="gevaar"
            autoFocus
            onClick={() => {
              setTeVerwijderen(menu.naam);
              setMenu(null);
            }}
          >
            Verwijderen…
          </button>
        </div>
      )}

      {teVerwijderen !== null && (
        <VerwijderDialoog
          project={teVerwijderen}
          onSluit={() => setTeVerwijderen(null)}
          onStart={() => sluitAls(teVerwijderen)}
          onKlaar={(uit) => {
            setTeVerwijderen(null);
            setVerwijderd(uit);
            void haalLijst();
          }}
        />
      )}

      {terugTeZetten !== null && (
        <TerugzetDialoog
          pad={terugTeZetten}
          onSluit={() => setTerugTeZetten(null)}
          onKlaar={(uit) => void naTerugzetten(uit)}
        />
      )}

      <main className="hoofd">
        <div className="hoofd-kop">
          <div>
            <h1>Media</h1>
            <p>
              {gekozen === null
                ? "Kies een project links, of sleep video's hierheen voor een nieuw project."
                : clips === null
                ? "Clips ophalen…"
                : clips.length === 0
                  ? "Nog geen clips in dit project."
                  : `${aantalAan} van ${clips.length} clips gekozen · klik op een clip om hem uit of aan te zetten`}
            </p>
          </div>
          <button className="knop" onClick={() => void kiesBestanden()} disabled={bezigToevoegen}>
            + Clips toevoegen
          </button>
        </div>

        {fout !== null && (
          <div className="melding-fout" role="alert">
            <b>Dat ging niet goed</b>
            <span className="mono">{fout}</span>
            <button className="knop-klein" onClick={() => setFout(null)}>
              Sluiten
            </button>
          </div>
        )}

        {wacht !== null && huidige !== null && (
          <div className="melding-fout let-op" role="status">
            <b>{wacht.kop}</b>
            <span>{wacht.uitleg}</span>
            <button className="knop-klein" disabled={bezig} onClick={() => void verderZonder(huidige.naam)}>
              Verder zonder
            </button>
          </div>
        )}

        <div className="clip-vlak">
          {clips === null ? (
            <div className="raster">
              {Array.from({ length: SKELETONS }, (_, i) => (
                <div className="clipkaart skelet" key={i}>
                  <div className="beeld" />
                  <div className="regel">
                    <span className="balkje" />
                    <span className="balkje kort" />
                  </div>
                </div>
              ))}
            </div>
          ) : clips.length === 0 ? (
            <div className="sleepvlak">
              <Sleeppictogram />
              <b>Sleep je clips hierheen</b>
              <span>
                Losse bestanden of een hele map. {EDITIE.naam} maakt proxies, meet beweging, scherpte,
                gezichten en GPS, en laat de bronbestanden ongemoeid.
              </span>
              <button
                className="knop-primair"
                onClick={() => void kiesBestanden()}
                disabled={bezigToevoegen}
              >
                + Clips toevoegen
              </button>
            </div>
          ) : (
            <div className="raster">
              {clips.map((c) => (
                <button
                  key={c.naam}
                  className={`clipkaart${c.aan ? " aan" : ""}${c.fout ? " onleesbaar" : ""}`}
                  aria-pressed={c.aan}
                  disabled={!!c.fout}
                  onClick={() => void zet(c)}
                  title={c.fout ? `${c.naam} — ${c.fout}` : c.naam}
                >
                  <div className="beeld">
                    {c.thumbnail !== null ? (
                      <img src={convertFileSrc(c.thumbnail)} alt="" loading="lazy" />
                    ) : (
                      <div className="geen-beeld" />
                    )}
                    <span className="duur mono">{c.fout ? "niet te lezen" : duurTekst(c.duur)}</span>
                    {c.aan && (
                      <span className="vink" aria-hidden="true">
                        <svg width="12" height="12" viewBox="0 0 12 12">
                          <path
                            d="M2.5 6.2l2.3 2.3 4.7-5"
                            fill="none"
                            stroke="var(--on-accent)"
                            strokeWidth="1.8"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </span>
                    )}
                  </div>
                  <div className="regel">
                    <span className="naam">{c.naam}</span>
                    <span className={`mono score${(c.score ?? 0) >= GOED ? " goed" : ""}`}>
                      {scoreTekst(c.score)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="onderbalk">
          <div className="balk-tekst">
            <div className="regel">
              <span className="stap-naam">
                {voortgang !== null
                  ? STAP_TEKST[voortgang.stap]
                  : bezigToevoegen
                    ? "Clips kopiëren"
                    : analyseKlaar
                      ? "Analyse klaar"
                      : clips === null || clips.length === 0
                        ? "Nog geen beelden"
                        : "Nog niet geanalyseerd"}
              </span>
              <span className="detail">
                {voortgang !== null
                  ? `${voortgang.totaal > 0 ? `${voortgang.gedaan}/${voortgang.totaal} · ` : ""}${voortgang.tekst}`
                  : "proxies · beweging · scherpte · gezichten · GPS"}
              </span>
              {tijden !== null && <span className="tijden mono">{tijden}</span>}
            </div>
            <div className="voortgangsbalk">
              <div
                className={`vulling${bezig && deel === null ? " pendelt" : ""}`}
                style={{
                  // Onbekend is niet "vol": dan pendelt de balk, en een
                  // stand van 1 zou bij uitgezette beweging een volle balk
                  // tonen terwijl er net begonnen is.
                  "--deel": bezig ? (deel ?? 0) : analyseKlaar ? 1 : 0,
                } as CSSProperties}
              />
            </div>
          </div>
          <button className="knop-groot" onClick={naarStijl} disabled={!kanDoor}>
            Verder: stijl en muziek →
          </button>
        </div>
      </main>

      {sleept && (
        <div className="sleep-markering" role="status">
          <div>
            <Sleeppictogram />
            <b>Laat los om toe te voegen</b>
            <span>{gekozen !== null ? `aan "${gekozen}"` : "er komt meteen een nieuw project"}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Sleeppictogram() {
  return (
    <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden="true" className="sleep-icoon">
      <rect
        x="2.5"
        y="5"
        width="19"
        height="14"
        rx="2.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path
        d="M12 15V9m0 0L9.4 11.6M12 9l2.6 2.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Eerste vrije naam als "video-3-okt", "video-3-okt-2", ... (zoals de engine mapnamen maakt). */
function vrijeNaam(lijst: { naam: string }[] | null): string {
  const d = new Date();
  const maand = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"][d.getMonth()];
  const basis = `video-${d.getDate()}-${maand}`;
  const bezet = new Set((lijst ?? []).map((p) => p.naam.toLowerCase()));
  if (!bezet.has(basis.toLowerCase())) return basis;
  for (let i = 2; ; i++) {
    const n = `${basis}-${i}`;
    if (!bezet.has(n.toLowerCase())) return n;
  }
}
