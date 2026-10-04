// Stap 4 — Bijwerken: de montage zien liggen op de beat en bijsturen.
// Ontwerp: ontwerp/beatcut2/Main.dc.html, scherm "4. BIJWERKEN".
//
// Alles op dit scherm hangt aan `project.montage`: de tijdlijn, de inspecteur
// en de voorvertoning lezen dezelfde stand. Elke wijziging stuurt de hele
// montage terug (shot.zet, regisseer) en die vervangt de stand in één keer —
// twee administraties van dezelfde montage is er één te veel.
//
// Wat hier níet kan: een shot verschuiven of langer maken. De tijdlijnpositie
// komt uit de muziek; alleen *wat* je in dat vak ziet is een keuze. Zie de
// toelichting boven `engine/cve/bijwerken.py`.
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  projectClipVoorkeur,
  projectMontage,
  projectRegisseer,
  projectShotZet,
  type Montagestand,
  type Shot,
  type Vorm,
} from "./engine";
import { duurTekst, getal } from "./format";
import Speler from "./speler/Speler";

/** De snelheden uit het ontwerp. De engine klemt op 0,25–2×. */
const SNELHEDEN = [0.25, 0.5, 1, 1.5, 2];
/** Hoeveel het highlight-venster opschuift per klik op ← of →. */
const STAP = 0.5;
/** Zoveel beeldjes van de filmstrip tonen we; de strook zelf heeft er 24. */
const STRIP_TONEN = 8;
/** Leesbare namen voor de gemeten signalen uit de analyse.
 *
 *  De sleutels zijn die van `stijl.Gewichten`. Drie ervan tellen negatief mee:
 *  trillen, een vlak beeld en een te donker beeld maken een shot slechter. Die
 *  tonen we omgekeerd (`om`), zodat een lange balk hier altijd "goed" betekent
 *  — met de ruwe waarde las een volle balk bij "Trillen" als lof. */
const SIGNAAL: Record<string, { label: string; om?: true; uitleg: string }> = {
  beweging: { label: "Beweging", uitleg: "Hoeveel er in het beeld gebeurt." },
  scherpte: { label: "Scherpte", uitleg: "Hoe scherp het beeld staat." },
  belichting: { label: "Belichting", uitleg: "Hoe goed het beeld belicht is." },
  gezicht: { label: "Gezicht in beeld", uitleg: "Of er iemand in beeld staat." },
  geluid: { label: "Eigen geluid", uitleg: "Hoeveel geluid er op de clip zelf staat." },
  shake: { label: "Stabiel", om: true, uitleg: "Omgekeerd: hoe minder het trilt, hoe langer de balk." },
  vlakheid: { label: "Detail", om: true, uitleg: "Omgekeerd: een vlak, saai beeld geeft een korte balk." },
  te_donker: { label: "Helder", om: true, uitleg: "Omgekeerd: hoe donkerder het beeld, hoe korter de balk." },
};

/** De signalen zoals ze getoond worden: nette naam, en negatieve omgedraaid. */
function signalen(ruw: Record<string, number>) {
  return Object.entries(ruw)
    .map(([naam, waarde]) => {
      const s = SIGNAAL[naam];
      return {
        naam,
        label: s?.label ?? naam,
        uitleg: s?.uitleg ?? "",
        waarde: Math.max(0, Math.min(1, s?.om ? 1 - waarde : waarde)),
      };
    })
    .sort((a, b) => b.waarde - a.waarde);
}

type Props = {
  project: string | null;
  keuze: { stijl: string; montage: string; vorm: Vorm["naam"]; duur: number | null };
  /** Legt de montage vast, gaat naar Exporteren en start de render. */
  onMaakVideo: () => void;
  naarStijl: () => void;
};

export default function Bijwerken({ project, keuze, onMaakVideo, naarStijl }: Props) {
  const [stand, setStand] = useState<Montagestand | null>(null);
  const [laadt, setLaadt] = useState(true);
  const [gekozen, setGekozen] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [uitleg, setUitleg] = useState<string | null>(null);
  const [tijd, setTijd] = useState(0);

  useEffect(() => {
    if (project === null) return;
    setLaadt(true);
    setStand(null);
    setGekozen(null);
    projectMontage(project)
      .then(setStand)
      .catch((e) => setFout(String(e)))
      .finally(() => setLaadt(false));
  }, [project]);

  const shots = stand?.shots ?? [];
  const shot: Shot | null = shots.find((s) => s.id === gekozen) ?? shots[0] ?? null;
  const clip = shot && stand ? stand.clips[shot.clip] : null;

  // Een shot aanklikken neemt de speler mee naar dat moment. Niet de speler
  // zelf laten kiezen: de tijdlijn hieronder en de inspecteur rechts moeten
  // dezelfde stand tonen, en dat is deze.
  const spring = shot ? shot.start : null;

  async function doe<T>(werk: () => Promise<T>, dan: (uit: T) => void) {
    setBezig(true);
    setFout(null);
    try {
      dan(await werk());
    } catch (e) {
      setFout(String(e));
    } finally {
      setBezig(false);
    }
  }

  function schuif(richting: -1 | 1) {
    if (project === null || !shot) return;
    void doe(
      () => projectShotZet(project, shot.id, { bron_in: shot.bron_in + richting * STAP }),
      setStand,
    );
  }

  function zetSnelheid(snelheid: number) {
    if (project === null || !shot) return;
    void doe(() => projectShotZet(project, shot.id, { snelheid }), setStand);
  }

  function zetVoorkeur(soort: "moet" | "nooit") {
    if (project === null || !shot || !stand) return;
    const aan = soort === "moet" ? shot.moet : shot.nooit;
    void doe(
      async () => {
        await projectClipVoorkeur(project, shot.bestand, aan ? null : soort);
        return projectMontage(project);
      },
      (m) => m && setStand(m),
    );
  }

  function opnieuw() {
    if (project === null) return;
    void doe(
      () =>
        projectRegisseer(
          project, keuze.stijl || undefined, keuze.montage || undefined,
          keuze.vorm, keuze.duur,
        ),
      (uit) => {
        setStand(uit.montage);
        setGekozen(null);
        setUitleg([uit.uitleg, ...uit.waarschuwingen].filter(Boolean).join(" "));
      },
    );
  }

  if (laadt) return <div className="binnenkort"><div>De montage ophalen…</div></div>;
  if (project === null || stand === null || shots.length === 0) {
    return (
      <div className="binnenkort">
        <div>
          <b>Er is nog geen montage</b>
          Kies eerst een stijl en muziek; dan ligt hier de tijdlijn.
          {fout && <p className="mono">{fout}</p>}
          <p><button className="knop" onClick={naarStijl}>Naar Stijl</button></p>
        </div>
      </div>
    );
  }

  const tellen = stand.tellen.length;
  // 106 maatnummers naast elkaar op 1800 px lopen in elkaar over en zijn
  // onleesbaar. De streepjes blijven voor elke maat staan — dat is het raster —
  // maar een nummer komt er maar om de zoveel maat bij.
  const maatStap = Math.max(1, Math.ceil(stand.maten.length / 24));
  const frac = stand.duur > 0 ? Math.min(1, Math.max(0, tijd / stand.duur)) : 0;

  return (
    <div className="bijwerken">
      <div className="bovenhelft">
        <section className="podium-shot">
          <Speler stand={stand} onTijd={setTijd} zoekNaar={spring} />
          <div className="speler-regel">
            <span className="noot">
              {stand.stijl} · {stand.vorm} · {stand.bpm ? `${Math.round(stand.bpm)} BPM` : "geen BPM"}
              {stand.muziek.bestand ? ` · ${stand.muziek.bestand}` : ""}
            </span>
          </div>
          {uitleg && <p className="kleine-noot">{uitleg}</p>}
        </section>

        <aside className="zijbalk inspecteur">
          {fout && (
            <div className="melding-fout">
              <b>Dat ging niet goed</b>
              <span className="mono">{fout}</span>
            </div>
          )}
          {shot && clip && (
            <>
              <div className="shot-kop">
                <div>
                  <b>{shot.bestand}</b>
                  <span>
                    Shot {shot.nr} van {shots.length} · {shot.tellen} tellen · bron{" "}
                    {duurTekst(clip.duur)}
                  </span>
                </div>
                <span className="mono score">
                  {shot.score === null ? "—" : getal(shot.score)}
                </span>
              </div>

              <div className="groep">
                <span className="kop-klein">Highlight</span>
                <div className="filmstrip">
                  <div className="strip">
                    {Array.from({ length: STRIP_TONEN }, (_, i) => (
                      <span
                        key={i}
                        className="frame"
                        style={
                          clip.strip
                            ? {
                                backgroundImage: `url(${convertFileSrc(clip.strip)})`,
                                backgroundSize: `${clip.strip_frames * 100}% 100%`,
                                backgroundPositionX: `${(i / (STRIP_TONEN - 1)) * 100}%`,
                              }
                            : undefined
                        }
                      />
                    ))}
                  </div>
                  <Scorelijn punten={clip.score} duur={clip.duur} />
                  <div
                    className="venster"
                    style={{
                      left: `${(shot.bron_in / Math.max(0.001, clip.duur)) * 100}%`,
                      width: `${(shot.bron_duur / Math.max(0.001, clip.duur)) * 100}%`,
                    }}
                  />
                </div>
                <div className="strip-regel">
                  <span className="kleine-noot">Lijn = score door de clip · kader = wat erin komt</span>
                  <div className="knop-rij">
                    <button className="knop-klein-rand" onClick={() => schuif(-1)} disabled={bezig} aria-label="Venster eerder">←</button>
                    <button className="knop-klein-rand" onClick={() => schuif(1)} disabled={bezig} aria-label="Venster later">→</button>
                  </div>
                </div>
              </div>

              <div className="vorm-raster">
                <button
                  className="keuzeknop"
                  aria-pressed={shot.moet}
                  onClick={() => zetVoorkeur("moet")}
                  disabled={bezig}
                >
                  Moet erin
                </button>
                <button
                  className="keuzeknop"
                  aria-pressed={shot.nooit}
                  onClick={() => zetVoorkeur("nooit")}
                  disabled={bezig}
                >
                  Nooit gebruiken
                </button>
              </div>

              <div className="groep">
                <span className="kop-klein">Snelheid</span>
                <div className="segment">
                  {SNELHEDEN.map((s) => (
                    <button
                      key={s}
                      className="mono"
                      aria-pressed={Math.abs(shot.snelheid - s) < 0.01}
                      onClick={() => zetSnelheid(s)}
                      disabled={bezig}
                    >
                      {String(s).replace(".", ",")}×
                    </button>
                  ))}
                </div>
              </div>

              <div className="groep">
                <span className="kop-klein">Waarom dit shot</span>
                {signalen(shot.signalen).map((s) => (
                  <div className="signaal" key={s.naam} title={s.uitleg}>
                    <span>{s.label}</span>
                    <div className="balk">
                      <div className="vulling" style={{ "--deel": s.waarde } as CSSProperties} />
                    </div>
                    <span className="mono">{getal(s.waarde)}</span>
                  </div>
                ))}
                <span className="kleine-noot">Langer is beter; drie zijn omgedraaid.</span>
                <span className="kleine-noot">{shot.reden}</span>
              </div>

              <div className="afsluiter">
                <button className="knop-groot vol" onClick={onMaakVideo} disabled={bezig}>
                  Maak video
                </button>
                <span className="kleine-noot">
                  De montage staat al vast in <span className="mono">edl.json</span>; dit rendert
                  hem en kijkt hem na.
                </span>
              </div>
            </>
          )}
        </aside>
      </div>

      <div className="tijdlijn">
        <div className="tijdlijn-kop">
          <button className="knop-klein-rand" onClick={opnieuw} disabled={bezig}>
            {bezig ? "Bezig…" : "Opnieuw regisseren"}
          </button>
          <span className="kleine-noot">
            {tellen} tellen · {stand.maten.length} maten · klik een shot om het te bewerken
          </span>
        </div>
        <div className="sporen">
          <div className="spoor">
            <span className="label" />
            <div className="maatbalk">
              {stand.maten.map((m) => (
                <span
                  key={m.nummer}
                  className="maat"
                  style={{ left: `${(m.t / Math.max(0.001, stand.duur)) * 100}%` }}
                >
                  {(m.nummer - 1) % maatStap === 0 ? m.nummer : ""}
                </span>
              ))}
            </div>
          </div>

          <div className="spoor">
            <span className="label">Beeld</span>
            <div className="beeldspoor">
              {shots.map((s) => (
                <button
                  key={s.id}
                  className="shot"
                  style={{ flexGrow: s.duur }}
                  aria-pressed={s.id === shot?.id}
                  aria-label={`Shot ${s.nr}, ${s.bestand}, ${s.tellen} tellen`}
                  onClick={() => setGekozen(s.id)}
                >
                  {s.thumbnail ? (
                    <img src={convertFileSrc(s.thumbnail)} alt="" />
                  ) : (
                    <span className="geen-beeld" />
                  )}
                  {s.moet && <span className="speld" />}
                  {s.nooit && <span className="kruis">✕</span>}
                  {s.snelheid !== 1 && (
                    <span className="mono snelheid">{String(s.snelheid).replace(".", ",")}×</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Een leeg spoor is alleen maar een lege strook: weg ermee tot er
              titels zijn. Die komen er pas met de AI-titelstap. */}
          {stand.titels.length > 0 && (
          <div className="spoor">
            <span className="label">Titels</span>
            <div className="titelspoor">
              {stand.titels.map((t) => (
                <span
                  key={t.id}
                  style={{
                    left: `${(t.start / Math.max(0.001, stand.duur)) * 100}%`,
                    width: `${(t.duur / Math.max(0.001, stand.duur)) * 100}%`,
                  }}
                  title={`${t.soort} · ${duurTekst(t.start)}`}
                >
                  {t.tekst || t.soort}
                </span>
              ))}
            </div>
          </div>
          )}

          <div className="spoor">
            <span className="label">
              Muziek
              <span className="mono">{stand.muziek.bestand ?? "—"}</span>
            </span>
            <div className="golfspoor">
              {stand.golfvorm.map((v, i) => (
                <span key={i} style={{ height: `${Math.max(6, v * 100)}%` }} />
              ))}
            </div>
          </div>

          <div className="naaldvlak">
            <div className="naald" style={{ left: `${frac * 100}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** De scorelijn door de clip, onder de filmstrip. Hoger is beter.
 *
 *  Twee dingen die hem eerst onzichtbaar maakten. Hij werd genormaliseerd op
 *  zijn eigen hoog en laag, dus bij twee meetpunten liep hij altijd van onder
 *  naar boven — dat zegt niets. En hij begon pas bij het eerste meetpunt, dus
 *  bij een clip met drie segmenten hing er een kort streepje in het midden van
 *  een verder leeg vak. Nu: vaste schaal 0..1 (zo komen de scores binnen) en
 *  doorgetrokken tot beide randen. */
function Scorelijn({ punten, duur }: { punten: { t: number; waarde: number }[]; duur: number }) {
  const { lijn, vlak } = useMemo(() => {
    if (punten.length === 0 || duur <= 0) return { lijn: "", vlak: "" };
    const rand = [
      { t: 0, waarde: punten[0].waarde },
      ...punten,
      { t: duur, waarde: punten[punten.length - 1].waarde },
    ];
    const xy = rand.map((p) => {
      const x = (Math.max(0, Math.min(duur, p.t)) / duur) * 100;
      const y = 46 - Math.max(0, Math.min(1, p.waarde)) * 38;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return { lijn: xy.join(" "), vlak: `0,50 ${xy.join(" ")} 100,50` };
  }, [punten, duur]);
  if (!lijn) return null;
  return (
    <svg className="scorelijn" viewBox="0 0 100 50" preserveAspectRatio="none" aria-hidden="true">
      <polygon points={vlak} fill="var(--accent-soft)" />
      <polyline
        points={lijn}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
