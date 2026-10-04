// Stap 5 — Exporteren: de montage zien ontstaan en daarna echt bekijken.
// Ontwerp: ontwerp/beatcut2/Main.dc.html, scherm EXPORTEREN.
//
// Het formaat staat hier alleen te lezen; wijzigen gebeurt in Stijl (besluit
// Koen, PLAN-v2.md §4): de regisseur kadert elk shot op dat formaat.
import { useEffect, useState, type CSSProperties } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { bytesTekst, duurTekst } from "./format";
import { exportOordeel, motorstand, type Titelstand } from "./exportkeuze";
import {
  projectMontage,
  projectVideo,
  type Montage,
  type Montagestand,
  type ReviewRegel,
  type Video,
  type Voortgang,
} from "./engine";
import Speler from "./speler/Speler";
import type { useOnderdelen } from "./onderdelen";
import type { Keuze } from "./Stijl";

export type Kwaliteit = "preview" | "eind";

/** Waar de montage van dít project nu staat. Woont in App, want de
 *  gebeurtenissen komen binnen terwijl dit scherm nog niet getekend is. */
export type MontageStand =
  | { soort: "bezig"; kwaliteit: Kwaliteit; voortgang: Voortgang | null }
  | { soort: "klaar"; montage: Montage }
  | { soort: "fout"; bericht: string }
  | null;

/** De zes fasen uit voortgang.RENDER_FASEN, teruggebracht tot wat een mens
 *  wil weten: wordt er bedacht, gerenderd of nagekeken. */
const GROEPEN = [
  { id: "regie", label: "De montage bedenken", fasen: ["voorbereiden"] },
  { id: "render", label: "Beelden renderen", fasen: ["blokken", "samenstellen", "geluid", "titels"] },
  { id: "nakijken", label: "De video nakijken", fasen: ["nakijken"] },
] as const;

const isMac = navigator.userAgent.includes("Mac");
const TOON_IN = isMac ? "Toon in Finder" : "Toon in Verkenner";

/** Wat er te zien is, of het nu net gerenderd is of al op schijf stond. */
type Resultaat = {
  video: string;
  naam: string;
  duur: number;
  review: ReviewRegel[] | null;
  uitleg: string | null;
  bytes: number | null;
  /** Wat de render niet kon doen zonder te stoppen. Alleen bij een verse
   *  render: `project.video` bewaart dit niet, want het hoort bij die ene
   *  poging en niet bij het bestand. */
  waarschuwingen: string[];
};

function uitMontage(m: Montage): Resultaat {
  return {
    video: m.video,
    naam: m.video.split(/[\\/]/).pop() ?? m.video,
    duur: m.duur,
    review: m.review,
    uitleg: m.uitleg,
    bytes: null,
    waarschuwingen: m.waarschuwingen ?? [],
  };
}

function uitVideo(v: Video): Resultaat {
  return { video: v.video, naam: v.naam, duur: v.duur, review: v.review, uitleg: null,
           bytes: v.bytes, waarschuwingen: [] };
}

type Props = {
  project: string | null;
  keuze: Keuze;
  stand: MontageStand;
  /** De stand van node/HyperFrames/browser; zie `useOnderdelen`. */
  onderdelen: ReturnType<typeof useOnderdelen>;
  naarStijl: () => void;
  onVolleKwaliteit: () => void;
};

export default function Exporteren({
  project, keuze, stand, onderdelen, naarStijl, onVolleKwaliteit,
}: Props) {
  const [opSchijf, setOpSchijf] = useState<Resultaat | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  /** De montage uit `edl.json`. Zolang er nog geen render ligt is dít wat er te
   *  zien is: dezelfde speler als bij Bijwerken, met look, afwerking en titels.
   *  Een voorbeeld dat niet is wat er uit de render komt is erger dan geen
   *  voorbeeld (PLAN-v2.md §4.4) — en dat is precies waarom het de speler is
   *  en geen stilstaand beeld. */
  const [montage, setMontage] = useState<Montagestand | null>(null);
  /** Is de montagevraag gefaald? Dan weten we niet of er titels zijn — en dat
   *  is iets anders dan weten dat er geen zijn. Zie `exportkeuze.ts`. */
  const [montageMislukt, setMontageMislukt] = useState(false);
  /** Staat de vraag open of we zonder titels gaan exporteren? */
  const [vraagZonderTitels, setVraagZonderTitels] = useState(false);

  // Bij het openen van de stap: staat er al een render? Dan die meteen tonen.
  //
  // Eerst weggooien wat er stond. Bij een projectwissel is alles wat hier ligt
  // van het vórige project: speler, bestandsnaam en "Toon in Finder" wezen
  // anders naar de render van A onder de naam van B. De montagestand zelf
  // wordt in App.tsx leeggemaakt, want die woont daar.
  useEffect(() => {
    setOpSchijf(null);
    setFout(null);
    setMontage(null);
    setMontageMislukt(false);
    setVraagZonderTitels(false);
    if (project === null) return;
    let geldig = true;
    projectVideo(project)
      .then((v) => {
        if (geldig) setOpSchijf(v === null ? null : uitVideo(v));
      })
      .catch((e) => {
        if (geldig) setFout(String(e));
      });
    // De montage erbij, voor het geval er nog geen video is. Mislukt dit, dan
    // blijft het bij de uitleg hieronder; het is geen fout van de render.
    projectMontage(project)
      .then((m) => {
        if (geldig) setMontage(m);
      })
      .catch(() => {
        // Niet stil wegslikken: zonder deze stand zou een mislukte vraag voor
        // "geen titels" doorgaan en bleef de waarschuwing weg.
        if (geldig) setMontageMislukt(true);
      });
    return () => {
      geldig = false;
    };
  }, [project, stand?.soort]);

  if (project === null) {
    return (
      <div className="binnenkort">
        <div>
          <b>Nog geen project</b>
          Kies of maak er een bij Media.
        </div>
      </div>
    );
  }

  const bezig = stand?.soort === "bezig";
  const resultaat = stand?.soort === "klaar" ? uitMontage(stand.montage) : opSchijf;
  const melding = stand?.soort === "fout" ? stand.bericht : fout;

  /** Hoeveel titels er in deze montage staan — of dat we het nog niet weten.
   *  Zonder titels maakt een ontbrekende titelmotor niets uit; dat we het
   *  níet weten is geen reden om te zwijgen. */
  const titelstand: Titelstand = montage !== null
    ? { soort: "aantal", aantal: montage.titels.length }
    : montageMislukt
      ? { soort: "mislukt" }
      : { soort: "onbekend" };
  const aantalTitels = montage?.titels.length ?? 0;

  /** De render pas starten als de gebruiker weet wat hij krijgt.
   *
   *  Dit is de hele reden dat deze stap de stand van de onderdelen kent: eerst
   *  sloeg `render.py` de titels stil over en kwam er een video uit zonder
   *  tekst, terwijl de voorvertoning ze wél toonde. Liever één vraag dan een
   *  export waar de gebruiker pas later iets aan mist.
   *
   *  De beslissing zelf staat in `exportkeuze.ts`: "nog onbekend" en "niet
   *  gelukt" zijn daar iets anders dan "gecontroleerd en in orde". */
  const oordeel = exportOordeel(
    titelstand,
    motorstand(onderdelen.status, onderdelen.stand.soort),
  );
  const titelsLopenMis = oordeel === "vraag";

  function exporteer() {
    if (oordeel !== "ga") {
      if (oordeel === "vraag") setVraagZonderTitels(true);
      return;
    }
    onVolleKwaliteit();
  }

  return (
    <div className="werkvlak">
      <main className="podium">
        {melding !== null && (
          <div className="melding-fout" role="alert">
            <b>De montage is niet gelukt</b>
            <span className="mono">{melding}</span>
            <button className="knop-klein" onClick={() => setFout(null)}>
              Sluiten
            </button>
          </div>
        )}

        {resultaat !== null && resultaat.waarschuwingen.length > 0 && (
          <div className="melding-fout let-op" role="status">
            <b>Let op</b>
            {resultaat.waarschuwingen.map((w) => (
              <span key={w}>{w}</span>
            ))}
            <button className="knop-klein" onClick={() => void onderdelen.start()}>
              Klaarzetten
            </button>
          </div>
        )}

        {vraagZonderTitels && (
          <div className="melding-fout let-op" role="alert">
            <b>
              {aantalTitels === 1
                ? "De titel kan nog niet in de video"
                : `De ${aantalTitels} titels kunnen nog niet in de video`}
            </b>
            <span>
              {onderdelen.stand.soort === "bezig"
                ? `BeatCut is de titelmotor aan het klaarzetten (${Math.round(
                    onderdelen.stand.percentage,
                  )} %). Wacht je daarop, dan staan de titels straks wel in de export.`
                : "De browser die de titels tekent staat nog niet klaar. Dat is eenmalig ophalen; daarna werkt het offline."}
            </span>
            <div className="knoppen-naast">
              <button className="knop-klein" onClick={() => setVraagZonderTitels(false)}>
                Wachten
              </button>
              <button
                className="knop-klein"
                onClick={() => {
                  setVraagZonderTitels(false);
                  onVolleKwaliteit();
                }}
              >
                Zonder titels exporteren
              </button>
            </div>
          </div>
        )}

        {bezig ? (
          <Voortgangsweergave stand={stand} />
        ) : resultaat !== null ? (
          <div className="video-vlak">
            {/* key: anders blijft de speler op de vorige render hangen. */}
            <video
              key={resultaat.video}
              className="speler"
              src={convertFileSrc(resultaat.video)}
              controls
              preload="metadata"
            />
            <div className="video-regel">
              <span className="mono">{resultaat.naam}</span>
              <span>
                {duurTekst(resultaat.duur)}
                {resultaat.bytes !== null && ` · ${bytesTekst(resultaat.bytes)}`}
              </span>
            </div>
          </div>
        ) : montage !== null && montage.shots.length > 0 ? (
          <div className="video-vlak">
            <Speler stand={montage} />
            <div className="video-regel">
              <span>Voorvertoning van de montage — zo wordt de video.</span>
              <span>{duurTekst(montage.duur)}</span>
            </div>
          </div>
        ) : (
          <div className="sleepvlak">
            <b>Nog geen video</b>
            <span>
              Kies bij Stijl een montagestijl en muziek, en klik op “Maak video”. BeatCut bedenkt de
              montage, rendert hem en kijkt hem na.
            </span>
            <button className="knop-primair" onClick={naarStijl}>
              Naar Stijl
            </button>
          </div>
        )}
      </main>

      <aside className="zijbalk export">
        <div className="groep">
          <h1 className="stap-titel">Exporteren</h1>
          <p className="stap-uitleg">
            Hier staat wat er gemaakt is. Het formaat ligt vast vanuit Stijl.
          </p>
        </div>

        <div className="formaat-regel">
          <span className="formaat-links">
            <b>Formaat {keuze.vorm}</b>
            <span>gekozen in Stijl · de kaders zijn hierop gemaakt</span>
          </span>
          <button className="knop-klein-rand" onClick={naarStijl}>
            Wijzigen in Stijl
          </button>
        </div>

        {resultaat?.uitleg != null && (
          <div className="voetnoot">
            <b>Wat de regisseur deed</b>
            <span>{resultaat.uitleg}</span>
          </div>
        )}

        {resultaat?.review != null && resultaat.review.length > 0 && (
          <div className="groep">
            <div className="kop-klein">Nagekeken</div>
            <div className="review-lijst">
              {resultaat.review.map((r) => (
                <span key={r.naam} className={`review-regel ${r.ernst === "ok" ? "ok" : r.ok ? "let-op" : "mis"}`}>
                  <Teken ernst={r.ernst} ok={r.ok} />
                  <span>{r.tekst}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="afsluiter">
          <div className="knop-rij">
            <button
              className="knop-wit"
              disabled={resultaat === null}
              onClick={() => {
                if (resultaat !== null) {
                  revealItemInDir(resultaat.video).catch((e) => setFout(String(e)));
                }
              }}
            >
              {TOON_IN}
            </button>
            <button className="knop" onClick={naarStijl}>
              Opnieuw met andere stijl
            </button>
          </div>
          <button
            className="knop-groot vol"
            disabled={bezig || oordeel === "wacht"}
            onClick={exporteer}
          >
            {oordeel === "wacht" ? "Even controleren…" : "Exporteer op volle kwaliteit"}
          </button>
          {titelsLopenMis && (
            <span className="kleine-noot let-op">
              {montageMislukt
                ? "BeatCut kon niet nakijken of er titels in deze montage staan, en de titelmotor is nog niet klaar."
                : `${aantalTitels === 1 ? "Er staat 1 titel" : `Er staan ${aantalTitels} titels`} in deze montage, en de titelmotor is nog niet klaar.`}{" "}
              BeatCut vraagt het voor de zekerheid nog één keer voordat hij begint.
            </span>
          )}
          <span className="kleine-noot">
            Volle kwaliteit rendert uit je originele beelden in plaats van de proxies. Zelfde stijl,
            zelfde snedes — alleen scherper, en het duurt een stuk langer.
          </span>
        </div>
      </aside>
    </div>
  );
}

function Voortgangsweergave({ stand }: { stand: { kwaliteit: Kwaliteit; voortgang: Voortgang | null } }) {
  const vg = stand.voortgang;
  const nu = GROEPEN.findIndex((g) => (g.fasen as readonly string[]).includes(vg?.stap ?? "voorbereiden"));
  const procent = Math.round(vg?.percentage ?? 0);
  const resterend = vg?.resterend ?? null;

  return (
    <div className="maakt">
      <h2>{stand.kwaliteit === "eind" ? "Op volle kwaliteit renderen…" : "Je video wordt gemaakt"}</h2>
      <div className="maak-stappen">
        {GROEPEN.map((g, i) => {
          const staat = i < nu ? "klaar" : i === nu ? "bezig" : "wacht";
          return (
            <div className={`maak-stap ${staat}`} key={g.id}>
              <span className="bol">{staat === "klaar" ? "✓" : i + 1}</span>
              <span className="maak-tekst">
                <b>{g.label}</b>
                <span>
                  {staat === "bezig"
                    ? `${vg?.tekst ?? "bezig…"}${vg && vg.totaal > 0 ? ` · ${vg.gedaan}/${vg.totaal}` : ""}`
                    : staat === "klaar"
                      ? "klaar"
                      : "wacht"}
                </span>
              </span>
              {g.id === "render" && staat === "bezig" && <span className="mono procent">{procent}%</span>}
            </div>
          );
        })}
      </div>
      <div className="balk breed">
        <div
          className={`vulling${vg === null ? " pendelt" : ""}`}
          style={{ "--deel": vg === null ? 1 : procent / 100 } as CSSProperties}
        />
      </div>
      <span className="kleine-noot">
        {resterend != null && resterend > 0
          ? `Nog ongeveer ${duurTekst(resterend)} te gaan.`
          : "De engine draait op de achtergrond; dit venster blijft bruikbaar."}
      </span>
    </div>
  );
}

/** Een vinkje is alleen eerlijk als er niets op aan te merken is. Een
 *  waarschuwing ("5 shots staan stil") met een groen vinkje leest als lof. */
function Teken({ ernst, ok }: { ernst: string; ok: boolean }) {
  if (ernst !== "ok" && ok) {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
        <circle cx="6" cy="6" r="4.2" fill="none" stroke="var(--warn)" strokeWidth="1.6" />
        <path d="M6 4v2.6" stroke="var(--warn)" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="6" cy="8.4" r="0.8" fill="var(--warn)" />
      </svg>
    );
  }
  return ok ? (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path
        d="M2.5 6.2l2.3 2.3 4.7-5"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  ) : (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path
        d="M3 3l6 6M9 3l-6 6"
        fill="none"
        stroke="var(--warn)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
