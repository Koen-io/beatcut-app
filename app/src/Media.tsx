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
import {
  GEBEURTENIS,
  VIDEO_EXTENSIES,
  clipZet,
  projectClips,
  projectMaak,
  projectVerwerk,
  projectVoegToe,
  projecten,
  type Clip,
  type EngineGebeurtenis,
  type Project,
  type Voortgang,
} from "./engine";

const ONTHOUD = "beatcut.project";
/** Vanaf deze score krijgt een clip de accentkleur — zie het ontwerp. */
const GOED = 0.8;
const SKELETONS = 12;

const STAP_TEKST: Record<Voortgang["stap"], string> = {
  inlezen: "Beelden inlezen",
  analyseren: "Analyseren",
};

function scoreTekst(score: number | null): string {
  return score === null ? "—" : score.toFixed(2).replace(".", ",");
}

type Props = {
  naarStijl: () => void;
  /** De titelbalk toont de projectnaam; die woont hier, niet in App. */
  onProject: (naam: string | null) => void;
};

export default function Media({ naarStijl, onProject }: Props) {
  const [lijst, setLijst] = useState<Project[] | null>(null);
  const [gekozen, setGekozen] = useState<string | null>(() => localStorage.getItem(ONTHOUD));
  const [clips, setClips] = useState<Clip[] | null>(null);
  const [voortgang, setVoortgang] = useState<Voortgang | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [sleept, setSleept] = useState(false);
  const [nieuw, setNieuw] = useState("");
  const [bezigToevoegen, setBezigToevoegen] = useState(false);

  // De gebeurtenislistener hangt er één keer, maar moet wel weten welk
  // project nú open staat; een ref voorkomt dat hij telkens opnieuw hangt.
  const gekozenRef = useRef(gekozen);
  gekozenRef.current = gekozen;
  /** Project dat na de lopende ronde nóg een keer verwerkt moet worden. */
  const nogmaals = useRef<string | null>(null);

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
        const onthouden = localStorage.getItem(ONTHOUD);
        setGekozen(p.some((q) => q.naam === onthouden) ? onthouden : (p[0]?.naam ?? null));
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
    localStorage.setItem(ONTHOUD, gekozen);
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
      if (payload.gebeurtenis === "voortgang") {
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
      if (nogmaals.current === payload.data.project) {
        nogmaals.current = null;
        void projectVerwerk(payload.data.project).catch((e) => setFout(String(e)));
      }
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
        const start = await projectVerwerk(doel);
        if (start.gestart) {
          // De eerste voortgangsmelding kan even op zich laten wachten. Zonder
          // dit valt de onderbalk terug op "klaar" en flikkert de knop aan.
          setVoortgang({ werk: "verwerk", project: doel, stap: "inlezen", gedaan: 0, totaal: 0, tekst: "Starten…" });
        } else {
          // De engine was nog bezig met een vorige ronde. Die ronde heeft de
          // lijst met bronnen al vastgelegd, dus deze clips zitten er niet in:
          // na "klaar" moet er nog een ronde overheen.
          nogmaals.current = doel;
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
  const kanDoor = analyseKlaar && aantalAan > 0;

  return (
    <div className={`werkvlak${sleept ? " sleept" : ""}`}>
      <aside className="zijbalk">
        <div className="groep">
          <div className="kop-klein">Projecten</div>
          {lijst === null && <div className="lijst-leeg">Laden…</div>}
          {lijst?.length === 0 && <div className="lijst-leeg">Nog geen projecten</div>}
          {lijst?.map((p) => (
            <button
              key={p.naam}
              className="lijst-item"
              aria-pressed={p.naam === gekozen}
              onClick={() => setGekozen(p.naam)}
            >
              <span className="naam">{p.naam}</span>
              <span className="mono aantal">{p.aantal_clips}</span>
            </button>
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
        </div>

        <div className="voetnoot">
          <b>Lokaal</b>
          <span>
            Proxies, analyse en montage blijven op deze computer. Bronbestanden worden nooit
            aangeraakt.
          </span>
        </div>
      </aside>

      <main className="hoofd">
        <div className="hoofd-kop">
          <div>
            <h1>Media</h1>
            <p>
              {clips === null
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

        <div className="clip-vlak">
          {clips === null ? (
            <div className="raster">
              {Array.from({ length: SKELETONS }, (_, i) => (
                <div className="kaart skelet" key={i}>
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
                Losse bestanden of een hele map. BeatCut maakt proxies, meet beweging, scherpte,
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
                  className={`kaart${c.aan ? " aan" : ""}`}
                  aria-pressed={c.aan}
                  onClick={() => void zet(c)}
                  title={c.naam}
                >
                  <div className="beeld">
                    {c.thumbnail !== null ? (
                      <img src={convertFileSrc(c.thumbnail)} alt="" loading="lazy" />
                    ) : (
                      <div className="geen-beeld" />
                    )}
                    <span className="duur mono">{duurTekst(c.duur)}</span>
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
            </div>
            <div className="balk">
              <div
                className={`vulling${bezig && voortgang?.totaal === 0 ? " pendelt" : ""}`}
                style={{
                  "--deel": bezig
                    ? voortgang && voortgang.totaal > 0
                      ? voortgang.gedaan / voortgang.totaal
                      : 1
                    : analyseKlaar
                      ? 1
                      : 0,
                } as CSSProperties}
              />
            </div>
          </div>
          <button className="knop-groot" onClick={naarStijl} disabled={!kanDoor}>
            Maak mijn video →
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
