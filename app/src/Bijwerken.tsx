// Stap 4 — Bijwerken: de montage zien liggen op de beat en bijsturen.
// Ontwerp: ontwerp/beatcut2/Main.dc.html, scherm "4. BIJWERKEN".
//
// Alles op dit scherm hangt aan `project.montage`: de tijdlijn, de inspecteur
// en de voorvertoning lezen dezelfde stand. Elke wijziging stuurt de hele
// montage terug (shot.zet, regisseer) en die vervangt de stand in één keer —
// twee administraties van dezelfde montage is er één te veel.
//
// Monteren kan sinds 13-10-2026 ook: slepen om de volgorde te veranderen,
// een snede een tel opschuiven, knippen, weghalen, en alles ongedaan maken.
// Eén ding blijft heilig: een snede ligt op een tel. Zie de kop van
// `engine/cve/monteren.py`; de sneltoetsen staan in `monteertoets.ts`.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  projectAfstemmen,
  projectClipVoorkeur,
  projectMontage,
  projectOngedaan,
  projectOpnieuw,
  projectRegisseer,
  projectShotSplits,
  projectShotTrim,
  projectShotVerplaats,
  projectShotVerwijder,
  projectShotZet,
  type Montagestand,
  type Shot,
  type Vorm,
} from "./engine";
import { duurTekst, getal } from "./format";
import { heeftHandwerk, telHandwerk } from "./handwerk";
import { monteeractie, typtInVeld, type Monteeractie } from "./monteertoets";
import { afstemTekst, redenTekst } from "./afstemtekst";
import Ikoon from "./Ikoon";
import Speler from "./speler/Speler";
import Spraak from "./Spraak";
import Zijbalk from "./Zijbalk";

/** De snelheden uit het ontwerp. De engine klemt op 0,25–2×. */
const SNELHEDEN = [0.25, 0.5, 1, 1.5, 2];
/** Hoeveel het highlight-venster opschuift per klik op ← of →. */
const STAP = 0.5;
/** Zoveel beeldjes van de filmstrip tonen we; de strook zelf heeft er 24. */
const STRIP_TONEN = 8;
/** De vaste standen voor het kader, per as waarop er ruimte is. Welke as dat
 *  is zegt de engine (`shot.kader_as`) — die kent de verhoudingen. */
const KADERSTANDEN: Record<"x" | "y", [string, number][]> = {
  x: [["Links", 0], ["Midden", 0.5], ["Rechts", 1]],
  y: [["Boven", 0], ["Midden", 0.5], ["Onder", 1]],
};

/** Welke vaste stand staat er nu? `null` = automatisch, of een punt dat niet
 *  op een van de drie knoppen valt (dat is wat de engine zelf uitrekende). */
function kaderStand(shot: Shot): string | null {
  const as = shot.kader_as;
  if (!as || !shot.kader) return null;
  const punt = as === "y" ? shot.kader.y : shot.kader.x;
  if (punt === undefined) return null;
  return KADERSTANDEN[as].find(([, w]) => Math.abs(w - punt) < 0.001)?.[0] ?? null;
}
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
  audiopiek: { label: "Geluidspiek", uitleg: "Een kreet, klap of gelach: luider dan de rest van de clip." },
  actiepiek: { label: "Actiepiek", uitleg: "Hier gebeurt meer dan elders in de clip: de sprong, de bocht." },
  nieuwheid: { label: "Nieuw beeld", uitleg: "Hoe anders deze clip eruitziet dan de andere clips." },
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
  /** Mag de app internet op? Voor het ophalen van het spraakmodel. */
  online?: boolean;
};

export default function Bijwerken({ project, keuze, onMaakVideo, naarStijl, online = true }: Props) {
  const [stand, setStand] = useState<Montagestand | null>(null);
  // Zonder project valt er niets te laden; anders bleef hier voor altijd
  // "De montage ophalen…" staan.
  const [laadt, setLaadt] = useState(project !== null);
  const [gekozen, setGekozen] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [uitleg, setUitleg] = useState<string | null>(null);
  const [vraagOpnieuw, setVraagOpnieuw] = useState(false);
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
  // Klikken op de maatbalk zet de afspeelkop binnen een shot, zodat knippen
  // op de afspeelkop ook echt kan (15-10-2026: een shot kiezen zette de kop
  // altijd op het begin, en dan knipte "S" altijd in het midden).
  const [kopNaar, setKopNaar] = useState<number | null>(null);
  // Een ander shot gekozen (klik, pijltjes, na een handeling): de kop gaat
  // naar zijn begin. Behalve als de maatbalk dat shot zelf koos — dan blijft
  // de kop waar geklikt is.
  const kopVanBalk = useRef(false);
  useEffect(() => {
    if (kopVanBalk.current) {
      kopVanBalk.current = false;
      return;
    }
    setKopNaar(null);
  }, [spring]);
  function zoekOpBalk(e: React.MouseEvent<HTMLElement>) {
    if (!stand || stand.duur <= 0) return;
    const r = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / Math.max(1, r.width)));
    const t = frac * stand.duur;
    // Ook het shot onder de kop kiezen: anders knipte "S" het eerder gekozen
    // shot in het midden in plaats van dit shot op de kop (review 15-10-2026).
    const onder = shots.find((s) => t >= s.start && t < s.start + s.duur) ?? shots[shots.length - 1];
    if (onder && onder.id !== shot?.id) {
      kopVanBalk.current = true;
      setGekozen(onder.id);
    }
    setKopNaar(t);
  }

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

  // -- monteren ---------------------------------------------------------------
  const geschiedenis = stand?.geschiedenis ?? { terug: 0, vooruit: 0 };
  const [sleept, setSleeptState] = useState<string | null>(null);
  const [sleepOp, setSleepOp] = useState<number | null>(null);
  // Slepen met pointer-events, niet met HTML5 drag-and-drop: in de echte app
  // (WKWebView) vangt Tauri's bestands-drop dat af en gebeurde er niets, terwijl
  // het in Chrome wél werkte (gezien bij de eerste echte klikronde, 15-10-2026).
  // Refs naast de state: de handlers op `window` lezen de stand van nu.
  const sleeptRef = useRef<string | null>(null);
  const sleepOpRef = useRef<number | null>(null);
  const netGesleept = useRef(false);
  const startRef = useRef<{ id: string; x: number; y: number } | null>(null);
  const setSleept = (id: string | null) => {
    sleeptRef.current = id;
    setSleeptState(id);
  };
  const zetSleepOp = (i: number | null) => {
    sleepOpRef.current = i;
    setSleepOp(i);
  };

  function begin(e: React.PointerEvent, id: string) {
    netGesleept.current = false;
    if (bezig || e.button !== 0) return;
    startRef.current = { id, x: e.clientX, y: e.clientY };
  }

  useEffect(() => {
    const beweeg = (e: PointerEvent) => {
      const start = startRef.current;
      if (start === null) return;
      // Pas na een paar pixels is het slepen; anders is het een klik.
      if (sleeptRef.current === null) {
        if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < 6) return;
        setSleept(start.id);
        setGekozen(start.id);
      }
      const onder = document.elementFromPoint(e.clientX, e.clientY);
      const knop = onder?.closest<HTMLElement>("[data-shot-index]");
      const i = knop ? Number(knop.dataset.shotIndex) : null;
      if (i !== sleepOpRef.current) zetSleepOp(i);
    };
    const los = () => {
      const start = startRef.current;
      startRef.current = null;
      if (start === null || sleeptRef.current === null) return;
      // De klik die de browser na het loslaten stuurt is geen keuze. Die klik
      // komt meteen na `pointerup`; daarna gaat de vlag weer uit, ook als de
      // klik op een ander element landde (review 15-10-2026).
      netGesleept.current = true;
      window.setTimeout(() => (netGesleept.current = false), 0);
      const doel = sleepOpRef.current;
      if (doel === null) {
        setSleept(null);
        zetSleepOp(null);
        return;
      }
      zetNeer(doel);
    };
    window.addEventListener("pointermove", beweeg);
    window.addEventListener("pointerup", los);
    window.addEventListener("pointercancel", los);
    return () => {
      window.removeEventListener("pointermove", beweeg);
      window.removeEventListener("pointerup", los);
      window.removeEventListener("pointercancel", los);
    };
  });

  /** Na een handeling: het gekozen shot blijft gekozen als het er nog is,
   *  anders het shot dat nu op die plek staat. */
  function naHandeling(m: Montagestand, plek?: number) {
    setStand(m);
    if (gekozen && m.shots.some((s) => s.id === gekozen)) return;
    const i = Math.max(0, Math.min(m.shots.length - 1, plek ?? 0));
    setGekozen(m.shots[i]?.id ?? null);
  }

  function voerUit(actie: Monteeractie) {
    if (project === null || bezig) return;
    const i = shot ? shots.findIndex((s) => s.id === shot.id) : -1;
    switch (actie) {
      case "ongedaan":
        if (geschiedenis.terug > 0) void doe(() => projectOngedaan(project), (m) => naHandeling(m, i));
        return;
      case "opnieuw":
        if (geschiedenis.vooruit > 0) void doe(() => projectOpnieuw(project), (m) => naHandeling(m, i));
        return;
      case "vorig-shot":
        if (i > 0) setGekozen(shots[i - 1].id);
        return;
      case "volgend-shot":
        if (i >= 0 && i < shots.length - 1) setGekozen(shots[i + 1].id);
        return;
    }
    if (!shot) return;
    switch (actie) {
      case "splits": {
        // Op de afspeelkop als die in dit shot staat; anders het midden.
        const binnen = tijd > shot.start && tijd < shot.start + shot.duur;
        void doe(() => projectShotSplits(project, shot.id, binnen ? tijd : undefined), (m) => naHandeling(m, i));
        return;
      }
      case "verwijder":
        if (shots.length > 1) {
          void doe(() => projectShotVerwijder(project, shot.id), (m) => {
            setGekozen(null);
            naHandeling(m, Math.max(0, i - 1));
          });
        }
        return;
      case "snede-terug":
      case "snede-vooruit":
        if (i < shots.length - 1) {
          const stap = actie === "snede-vooruit" ? 1 : -1;
          void doe(() => projectShotTrim(project, shot.id, "eind", stap), (m) => naHandeling(m, i));
        }
        return;
    }
  }

  function trimRand(kant: "begin" | "eind", stap: -1 | 1) {
    if (project === null || !shot || bezig) return;
    const i = shots.findIndex((s) => s.id === shot.id);
    void doe(() => projectShotTrim(project, shot.id, kant, stap), (m) => naHandeling(m, i));
  }

  function zetNeer(doelIndex: number) {
    const van = sleeptRef.current;
    setSleept(null);
    zetSleepOp(null);
    if (project === null || van === null) return;
    const vanIndex = shots.findIndex((s) => s.id === van);
    if (vanIndex < 0 || vanIndex === doelIndex) return;
    void doe(() => projectShotVerplaats(project, van, doelIndex), (m) => {
      setStand(m);
      setGekozen(m.shots[doelIndex]?.id ?? null);
    });
  }

  // Sneltoetsen. Eén keer per render opnieuw aangehangen: de handlers lezen
  // de stand van dit moment, en een verouderde sluiting knipt het verkeerde shot.
  useEffect(() => {
    const op = (e: KeyboardEvent) => {
      if (typtInVeld(e.target as HTMLElement | null)) return;
      const actie = monteeractie(e);
      if (actie === null) return;
      e.preventDefault();
      voerUit(actie);
    };
    window.addEventListener("keydown", op);
    return () => window.removeEventListener("keydown", op);
  });

  function zetSnelheid(snelheid: number) {
    if (project === null || !shot) return;
    void doe(() => projectShotZet(project, shot.id, { snelheid }), setStand);
  }

  /** Herkaderen: waar het venster in de bron valt. `null` is automatisch —
   *  dan rekent de engine het opnieuw uit de aandachtspunten van de analyse. */
  function zetKader(punt: number | null) {
    if (project === null || !shot) return;
    const kader =
      punt === null ? {} : shot.kader_as === "y" ? { y: punt } : { x: punt };
    void doe(() => projectShotZet(project, shot.id, { kader }), setStand);
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

  /** "Opnieuw regisseren" gooit elk met de hand bijgestelde shot weg. Staat
   *  er zulk handwerk, dan eerst vragen; anders meteen doen. */
  function opnieuwGevraagd() {
    if (heeftHandwerk(shots)) {
      setVraagOpnieuw(true);
      return;
    }
    opnieuw();
  }

  function opnieuw() {
    if (project === null) return;
    setVraagOpnieuw(false);
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
          <Speler stand={stand} onTijd={setTijd} zoekNaar={kopNaar ?? spring} />
          <div className="speler-regel">
            <span className="noot">
              {stand.stijl} · {stand.vorm} · {stand.bpm ? `${Math.round(stand.bpm)} BPM` : "geen BPM"}
              {stand.muziek.bestand ? ` · ${stand.muziek.bestand}` : ""}
            </span>
          </div>
          {uitleg && <p className="kleine-noot">{uitleg}</p>}
        </section>

        <Zijbalk
          kant="rechts"
          sleutel="bijwerken"
          standaard={400}
          naam="het shotpaneel"
          klasse="inspecteur"
        >
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

              {shot.kader_as && (
                <div className="groep">
                  <span className="kop-klein">Kader</span>
                  <div className="segment">
                    <button
                      aria-pressed={!kaderStand(shot)}
                      onClick={() => zetKader(null)}
                      disabled={bezig}
                    >
                      Automatisch
                    </button>
                    {KADERSTANDEN[shot.kader_as].map(([label, waarde]) => (
                      <button
                        key={label}
                        aria-pressed={kaderStand(shot) === label}
                        onClick={() => zetKader(waarde)}
                        disabled={bezig}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <span className="kleine-noot">
                    Dit beeld is breder of hoger dan de video, dus er valt een stuk
                    weg. Automatisch volgt wie of wat er beweegt; kies zelf als dat
                    de verkeerde kant op gaat.
                  </span>
                </div>
              )}

              <div className="groep">
                <span className="kop-klein">Beeld bijwerken</span>
                <button
                  className="schakelaar"
                  role="switch"
                  aria-checked={stand.afstemmen ?? true}
                  disabled={bezig}
                  onClick={() => {
                    const aan = !(stand.afstemmen ?? true);
                    void doe(() => projectAfstemmen(project, aan), setStand);
                  }}
                >
                  <span>Clips op elkaar afstemmen</span>
                  <span className="wip" />
                </button>
                <span className="kleine-noot">
                  Helderheid en witbalans van elke clip naar die van de montage, vóór de look.
                  {(stand.afstemmen ?? true) ? ` ${afstemTekst(shot.kleur)}` : ""}
                </span>
                <button
                  className="schakelaar"
                  role="switch"
                  aria-checked={shot.stabiliseer ?? false}
                  disabled={bezig}
                  onClick={() =>
                    void doe(
                      () => projectShotZet(project, shot.id, { stabiliseer: !(shot.stabiliseer ?? false) }),
                      setStand,
                    )
                  }
                >
                  <span>Dit shot stabiliseren</span>
                  <span className="wip" />
                </button>
                <span className="kleine-noot">
                  Haalt trilling weg in de export (ffmpeg deshake). De voorvertoning laat het
                  origineel zien.
                  {(shot.signalen.shake ?? 0) > 0.4 ? " Dit shot trilt flink." : ""}
                </span>
              </div>

              <Spraak
                project={project}
                online={online}
                onVeranderd={() => {
                  void projectMontage(project).then((m) => m && setStand(m)).catch((e) => setFout(String(e)));
                }}
              />

              <div className="groep">
                <span className="kop-klein">Waarom dit shot</span>
                {signalen(shot.signalen).map((s) => (
                  <div className="signaal" key={s.naam} title={s.uitleg}>
                    <span>{s.label}</span>
                    <div className="voortgangsbalk">
                      <div className="vulling" style={{ "--deel": s.waarde } as CSSProperties} />
                    </div>
                    <span className="mono">{getal(s.waarde)}</span>
                  </div>
                ))}
                <span className="kleine-noot">Langer is beter; drie zijn omgedraaid.</span>
                <span className="kleine-noot">
                  {redenTekst(shot.reden, Object.fromEntries(Object.entries(SIGNAAL).map(([k, v]) => [k, v.label])))}
                </span>
              </div>

              <div className="afsluiter">
                <span className="route" aria-hidden="true">
                  <b>2 Stijl</b>→<b>3 Look</b>→<b className="nu">4 Bijwerken</b>→<b>5 Exporteren</b>
                </span>
                <button className="knop-groot vol" onClick={onMaakVideo} disabled={bezig}>
                  Maak video →
                </button>
                <span className="kleine-noot">
                  De montage staat al vast in <span className="mono">edl.json</span>; dit rendert
                  hem en kijkt hem na.
                </span>
              </div>
            </>
          )}
        </Zijbalk>
      </div>

      <div className="tijdlijn">
        <div className="tijdlijn-kop">
          {vraagOpnieuw ? (
            <span className="bevestiging" role="alertdialog" aria-label="Opnieuw regisseren?">
              <span>
                {telHandwerk(shots) === 1
                  ? "1 shot met handwerk gaat verloren."
                  : `${telHandwerk(shots)} shots met handwerk gaan verloren.`}
              </span>
              <button className="knop-klein" onClick={opnieuw} disabled={bezig}>
                Toch opnieuw
              </button>
              <button className="knop-klein-rand" onClick={() => setVraagOpnieuw(false)}>
                Laat staan
              </button>
            </span>
          ) : (
            <button className="knop-klein-rand" onClick={opnieuwGevraagd} disabled={bezig}>
              {bezig ? "Bezig…" : "Opnieuw regisseren"}
            </button>
          )}
          <span className="monteerbalk" role="toolbar" aria-label="Monteren">
            <button className="ikoonknop" onClick={() => voerUit("ongedaan")}
              disabled={bezig || geschiedenis.terug === 0} title="Ongedaan maken (⌘Z)"
              aria-label="Ongedaan maken"><Ikoon naam="ongedaan" /></button>
            <button className="ikoonknop" onClick={() => voerUit("opnieuw")}
              disabled={bezig || geschiedenis.vooruit === 0} title="Opnieuw (⇧⌘Z)"
              aria-label="Opnieuw"><Ikoon naam="opnieuw" /></button>
            <span className="scheiding" />
            <span className="randgroep" title="De snede vóór dit shot een tel verschuiven">
              <span className="randlabel">Begin</span>
              <button className="ikoonknop" onClick={() => trimRand("begin", -1)}
                disabled={bezig || !shot || shots[0]?.id === shot.id}
                title="Begin een tel eerder" aria-label="Begin een tel eerder"><Ikoon naam="links" /></button>
              <button className="ikoonknop" onClick={() => trimRand("begin", 1)}
                disabled={bezig || !shot || shots[0]?.id === shot.id}
                title="Begin een tel later" aria-label="Begin een tel later"><Ikoon naam="rechts" /></button>
            </span>
            <button className="ikoonknop" onClick={() => voerUit("splits")}
              disabled={bezig || !shot || (shot.tellen ?? 1) < 2}
              title="Knippen op de afspeelkop (S)" aria-label="Knippen"><Ikoon naam="knip" /></button>
            <span className="randgroep" title="De snede ná dit shot een tel verschuiven">
              <button className="ikoonknop" onClick={() => trimRand("eind", -1)}
                disabled={bezig || !shot || shots[shots.length - 1]?.id === shot.id}
                title="Eind een tel eerder (,)" aria-label="Eind een tel eerder"><Ikoon naam="links" /></button>
              <button className="ikoonknop" onClick={() => trimRand("eind", 1)}
                disabled={bezig || !shot || shots[shots.length - 1]?.id === shot.id}
                title="Eind een tel later (.)" aria-label="Eind een tel later"><Ikoon naam="rechts" /></button>
              <span className="randlabel">Eind</span>
            </span>
            <span className="scheiding" />
            <button className="ikoonknop" onClick={() => voerUit("verwijder")}
              disabled={bezig || !shot || shots.length < 2}
              title="Shot weghalen (⌫)" aria-label="Shot weghalen"><Ikoon naam="weg" /></button>
          </span>
          <span className="kleine-noot">
            {tellen} tellen · {stand.maten.length} maten · sleep een shot om de volgorde te veranderen
          </span>
        </div>
        <div className="sporen">
          <div className="spoor">
            <span className="label" />
            <div className="maatbalk" onClick={zoekOpBalk} title="Klik om de afspeelkop hier te zetten">
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
              {shots.map((s, i) => (
                <button
                  key={s.id}
                  className={`shot${sleept === s.id ? " sleept" : ""}${sleepOp === i && sleept !== s.id ? " sleepdoel" : ""}${sleepOp === i && sleept !== null && shots.findIndex((x) => x.id === sleept) < i ? " na" : ""}`}
                  style={{ flexGrow: s.duur }}
                  aria-pressed={s.id === shot?.id}
                  aria-label={`Shot ${s.nr}, ${s.bestand}, ${s.tellen} tellen`}
                  data-shot-index={i}
                  onClick={() => {
                    // Na een sleepbeweging is de klik die de browser erachteraan
                    // stuurt geen keuze.
                    if (netGesleept.current) {
                      netGesleept.current = false;
                      return;
                    }
                    setGekozen(s.id);
                  }}
                  onPointerDown={(e) => begin(e, s.id)}
                >
                  {s.thumbnail ? (
                    <img src={convertFileSrc(s.thumbnail)} alt="" draggable={false} />
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
