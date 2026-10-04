// Stap 2 — Stijl: welke montage, welk formaat, hoe lang, en op welke muziek.
// Ontwerp: ontwerp/beatcut2/Main.dc.html, scherm STIJL.
//
// Er staat bewust geen voorvertoning in het midden. Een nagemaakt beeld dat
// niet is wat er uit de render komt is erger dan geen beeld; de echte live
// voorvertoning komt met de compositor (PLAN-v2.md §4.4).
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import { bytesTekst, duurTekst } from "./format";
import {
  AUDIO_EXTENSIES,
  GEBEURTENIS,
  muziekGenereer,
  muziekInstalleer,
  muziekInstalleerStop,
  muziekKies,
  muziekStatus,
  projectMuziek,
  projectMuziekStand,
  projectStijlen,
  titelVoorbeelden,
  type EngineGebeurtenis,
  type Montagestijl,
  type Muziek,
  type MuziekStatus,
  type MuziekVariant,
  type Stijlen,
  type Titelstijl,
  type Vorm,
} from "./engine";

/** Wat stap 2 vastlegt en stap 5 alleen nog voorleest.
 *
 *  Twee stijllagen, zoals PLAN-v2.md §4: `stijl` is het **soort beelden**
 *  (wordt herkend, bepaalt wat een goed shot is), `montage` is de
 *  **montagestijl** (bepaalt het snijritme). Leeg = de engine kiest er een
 *  die bij het soort beelden past. */
export type Keuze = {
  stijl: string;
  montage: string;
  /** De titelstijl (twintig stuks, PLAN-v2.md §4.2). Leeg = de eerste uit de
   *  catalogus. Hij zit bewust niet in de brief van de regisseur: een andere
   *  titel is geen andere montage, alleen een nieuwe overlay. */
  titel: string;
  vorm: Vorm["naam"];
  duur: number | null;
};

const LENGTES: { label: string; duur: number | null }[] = [
  { label: "Past op muziek", duur: null },
  { label: "15 s", duur: 15 },
  { label: "30 s", duur: 30 },
  { label: "60 s", duur: 60 },
];

/** Zelf maken of een eigen bestand kiezen. De online catalogus uit het ontwerp
 *  staat er nog niet in: die wacht op het partnercontract (PLAN-v2.md §5). */
const BRONNEN: { sleutel: "gen" | "eigen"; label: string }[] = [
  { sleutel: "gen", label: "Genereren" },
  { sleutel: "eigen", label: "Eigen nummer" },
];

const VARIANTEN = 3;

/** De twee stijllagen als tabbladen, en het energiefilter boven de kaarten.
 *  Allebei uit het ontwerp (ontwerp/beatcut2/Main.dc.html, scherm STIJL). */
const BANDEN: { sleutel: string; label: string }[] = [
  { sleutel: "alles", label: "Alles" },
  { sleutel: "snel", label: "Snel" },
  { sleutel: "gemiddeld", label: "Gemiddeld" },
  { sleutel: "rustig", label: "Rustig" },
];

/** Vijf balkjes die oplopen; de eerste `energie` zijn aan. */
function Energie({ energie }: { energie: number }) {
  return (
    <span className="energie" aria-label={`Energie ${energie} van 5`}>
      {[1, 2, 3, 4, 5].map((k) => (
        <span key={k} className={k <= energie ? "aan" : ""} style={{ height: 6 + k * 4 }} />
      ))}
    </span>
  );
}

/** Een rechthoekje op schaal, zodat 9:16 er ook als 9:16 uitziet. */
export function VormIcoon({ vorm }: { vorm: Vorm }) {
  const max = 24;
  const schaal = max / Math.max(vorm.breedte, vorm.hoogte);
  return (
    <span
      className="vorm-icoon"
      style={{ width: Math.round(vorm.breedte * schaal), height: Math.round(vorm.hoogte * schaal) }}
    />
  );
}

type Props = {
  project: string | null;
  keuze: Keuze;
  setKeuze: (k: Keuze) => void;
  /** Start de montage en ga naar Exporteren. Zit in App, want de gebeurtenissen
   *  van de engine komen binnen terwijl dit scherm al weg is. */
  onMaakVideo: () => void;
  /** De schakelaar uit de titelbalk. Het muziekmodel moet één keer van
   *  internet komen, dus offline hoort die knop uit te staan. */
  online: boolean;
};

export default function Stijl({ project, keuze, setKeuze, onMaakVideo, online }: Props) {
  const [stijlen, setStijlen] = useState<Stijlen | null>(null);
  const [muziek, setMuziek] = useState<Muziek | null>(null);
  const [meet, setMeet] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  const [tab, setTab] = useState<"montage" | "titels" | "beelden">("montage");
  // De voorbeeldbeelden komen apart binnen: bij een lege cache is dat een
  // browserrender per stijl en dat duurt langer dan de lijst zelf.
  const [titelbeelden, setTitelbeelden] = useState<Titelstijl[] | null>(null);
  const [titelbezig, setTitelbezig] = useState(false);
  const [band, setBand] = useState("alles");
  const [bron, setBron] = useState<"gen" | "eigen">("gen");
  const [muziekmodel, setMuziekmodel] = useState<MuziekStatus | null>(null);
  const [genre, setGenre] = useState("House");
  const [zang, setZang] = useState(false);
  const [varianten, setVarianten] = useState<MuziekVariant[]>([]);
  const [componeert, setComponeert] = useState(false);
  const [genVoortgang, setGenVoortgang] = useState({ percentage: 0, tekst: "" });
  // Het ophalen van het model (11 GB) staat los van een project en los van de
  // generatie: het loopt machinebreed door, ook als je van project wisselt.
  const [installeert, setInstalleert] = useState(false);
  const [instFout, setInstFout] = useState<string | null>(null);
  const [instStand, setInstStand] = useState({
    stap: "", percentage: 0, tekst: "", gedaan: 0, totaal: 0,
  });
  // Eén speler voor alle varianten: twee tracks door elkaar is nooit wat
  // iemand bedoelt met op een afspeelknop drukken.
  const speler = useRef<HTMLAudioElement | null>(null);
  const [speelt, setSpeelt] = useState<string | null>(null);

  const haal = useCallback(async (naam: string) => {
    setFout(null);
    try {
      const [s, m, g] = await Promise.all([
        projectStijlen(naam),
        projectMuziekStand(naam),
        muziekStatus(naam),
      ]);
      setStijlen(s);
      setMuziek(m);
      setMuziekmodel(g);
      // Ligt er al een nummer, dan hoort de schakelaar op "Eigen nummer" te
      // staan: anders kijkt iemand naar een paneel vol genre-chips terwijl zijn
      // eigen track er gewoon in zit, en leest "Genereren" als wat er gebeurd is.
      setBron(m === null ? "gen" : "eigen");
      setVarianten(g.varianten ?? []);
      setComponeert(g.bezig === true);
      setInstalleert(g.installeren_bezig === true);
      return s;
    } catch (e) {
      setFout(String(e));
      setStijlen(null);
      return null;
    }
  }, []);

  // De herkende stijl is het voorstel, niet de wet: alleen als er nog niets
  // gekozen is schuift hij erin. Anders zou een terugklik de keuze opeten.
  useEffect(() => {
    if (project === null) return;
    setStijlen(null);
    setMuziek(null);
    setVarianten([]);
    stopSpelen();
    void haal(project).then((s) => {
      if (s === null) return;
      // Beide lagen krijgen hun voorstel, en alleen als er nog niets gekozen
      // is: anders eet een terugklik de keuze op.
      const nieuw = { ...keuze };
      if (s.herkend && nieuw.stijl === "") nieuw.stijl = s.herkend;
      if (s.montage_herkend && nieuw.montage === "") nieuw.montage = s.montage_herkend;
      if (nieuw.stijl !== keuze.stijl || nieuw.montage !== keuze.montage) setKeuze(nieuw);
    });
    // keuze mag hier niet in: dan draait dit bij elke klik opnieuw.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, haal]);

  // De voorbeeldbeelden, pas als iemand het tabblad opent: twintig renders
  // starten terwijl hij naar montagestijlen kijkt is werk voor niets.
  useEffect(() => {
    if (project === null || tab !== "titels" || titelbeelden !== null) return;
    setTitelbezig(true);
    void titelVoorbeelden(project)
      .then((r) => {
        setTitelbeelden(r.titelstijlen);
        // Alles er al? Dan is er niets gestart en komt er ook geen gebeurtenis.
        if (r.titelstijlen.every((x) => x.voorbeeld !== null)) setTitelbezig(false);
      })
      .catch((e) => {
        setFout(String(e));
        setTitelbezig(false);
      });
  }, [project, tab, titelbeelden]);

  useEffect(() => {
    const stop = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.werk !== "titelvoorbeelden") return;
      if (payload.gebeurtenis === "klaar") {
        setTitelbeelden(payload.data.titelstijlen);
        setTitelbezig(false);
      } else if (payload.gebeurtenis === "fout") {
        setTitelbezig(false);
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, []);

  // De installatie van het model heeft geen project: een eigen luisteraar, zonder
  // de projectfilter van de muziekgebeurtenissen hieronder.
  useEffect(() => {
    const stop = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.werk !== "muziekinstall") return;
      if (payload.gebeurtenis === "voortgang") {
        setInstalleert(true);
        // De bytetelling alleen bijwerken als er een is: niet elke stap heeft
        // bytes te melden, en dan hoort de regel niet weg te knipperen. Maar
        // bytes horen bij één stap: zonder de reset hieronder bleef "9 MB van
        // 14 MB" (de broncode-zip) onder "Pakketten installeren…" staan, en
        // daarna onder "Modelgewichten ophalen…". Gemeten 04-10-2026.
        setInstStand((v) => {
          const zelfdeStap = payload.data.stap === v.stap;
          const bytes = payload.data.totaal > 0;
          return {
            stap: payload.data.stap,
            percentage: payload.data.percentage ?? 0,
            tekst: payload.data.tekst,
            gedaan: bytes ? payload.data.gedaan : zelfdeStap ? v.gedaan : 0,
            totaal: bytes ? payload.data.totaal : zelfdeStap ? v.totaal : 0,
          };
        });
      } else if (payload.gebeurtenis === "klaar") {
        // Eerst de status, dán de balk weg. Andersom biedt de kaart een seconde
        // lang weer "Installeren" aan terwijl de installatie net klaar is.
        void muziekStatus(project ?? undefined)
          .then(setMuziekmodel)
          .catch(() => {})
          .finally(() => setInstalleert(false));
      } else if (payload.gebeurtenis === "fout") {
        setInstalleert(false);
        setInstFout(payload.data.fout);
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, [project]);

  async function installeerModel() {
    setInstFout(null);
    setInstStand({ stap: "", percentage: 0, tekst: "Beginnen…", gedaan: 0, totaal: 0 });
    setInstalleert(true);
    try {
      // `gestart: false` betekent dat er al een installatie liep; dan is de
      // balk ook goed, want de voortgang daarvan komt hier binnen.
      await muziekInstalleer();
    } catch (e) {
      setInstalleert(false);
      setInstFout(String(e));
    }
  }

  async function stopInstallatie() {
    try {
      await muziekInstalleerStop();
    } catch (e) {
      setInstFout(String(e));
    }
  }

  // De BPM-meting van een net gekozen track komt als gebeurtenis terug.
  useEffect(() => {
    const stop = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.project !== project) return;
      if (payload.gebeurtenis === "klaar" && payload.data.werk === "muziek") {
        setMuziek(payload.data.muziek);
        setMeet(false);
      } else if (payload.gebeurtenis === "klaar" && payload.data.werk === "muziekgen") {
        setVarianten(payload.data.varianten);
        setComponeert(false);
      } else if (payload.gebeurtenis === "voortgang" && payload.data.werk === "muziekgen") {
        setGenVoortgang({
          percentage: payload.data.percentage ?? 0,
          tekst: payload.data.tekst,
        });
      } else if (payload.gebeurtenis === "fout") {
        setMeet(false);
        setComponeert(false);
        setFout(payload.data.fout);
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, [project]);

  async function kiesMuziek() {
    if (project === null) return;
    const pad = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "Muziek", extensions: AUDIO_EXTENSIES }],
    });
    if (typeof pad !== "string") return;
    setFout(null);
    try {
      const m = await projectMuziek(project, pad);
      setMuziek({ bestand: m.bestand, bpm: m.bpm, duur: m.duur });
      setMeet(m.gestart);
    } catch (e) {
      setFout(String(e));
    }
  }

  function stopSpelen() {
    speler.current?.pause();
    setSpeelt(null);
  }

  function speelAfOfStop(v: MuziekVariant) {
    if (speelt === v.pad) {
      stopSpelen();
      return;
    }
    const a = speler.current;
    if (a === null) return;
    a.src = convertFileSrc(v.pad);
    void a.play().then(() => setSpeelt(v.pad)).catch((e) => setFout(String(e)));
  }

  async function componeer() {
    if (project === null) return;
    setFout(null);
    setVarianten([]);
    stopSpelen();
    setGenVoortgang({ percentage: 0, tekst: "Muziekmodel laden…" });
    try {
      const r = await muziekGenereer(project, {
        genre,
        zang,
        varianten: VARIANTEN,
        // Geen BPM mee: de engine kiest er een bij de stijl en het genre.
        // Lengte: wat bij Lengte gekozen is, anders 30 s.
        duur: keuze.duur ?? 30,
        stijl: keuze.stijl || undefined,
      });
      setComponeert(r.gestart || r.bezig);
    } catch (e) {
      setFout(String(e));
    }
  }

  async function gebruikVariant(v: MuziekVariant) {
    if (project === null) return;
    setFout(null);
    stopSpelen();
    try {
      const m = await muziekKies(project, v.pad);
      setMuziek({ bestand: m.bestand, bpm: m.bpm ?? v.bpm, duur: m.duur ?? v.duur });
      setMeet(m.gestart);
    } catch (e) {
      setFout(String(e));
    }
  }

  const gekozenStijl = stijlen?.stijlen.find((s) => s.naam === keuze.stijl) ?? null;
  const gekozenMontage =
    stijlen?.montagestijlen.find((m) => m.id === keuze.montage) ?? null;
  const grens = stijlen?.banden[band] ?? [1, 5];
  const zichtbaar = (stijlen?.montagestijlen ?? []).filter(
    (m) => m.energie >= grens[0] && m.energie <= grens[1],
  );
  const gekozenVorm = stijlen?.vormen.find((v) => v.naam === keuze.vorm) ?? null;
  const titelId = keuze.titel || stijlen?.titel_gekozen || "";
  const gekozenTitel =
    (titelbeelden ?? stijlen?.titelstijlen ?? []).find((x) => x.id === titelId) ?? null;
  const lengte = LENGTES.find((l) => l.duur === keuze.duur) ?? LENGTES[0];
  const kanDoor =
    project !== null &&
    muziek !== null &&
    gekozenStijl !== null &&
    gekozenMontage !== null &&
    !meet &&
    !componeert;

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

  return (
    <div className="werkvlak">
      <aside className="zijbalk breed">
        <div className="groep">
          <h1 className="stap-titel">Stijl</h1>
          <p className="stap-uitleg">
            De montagestijl bepaalt hoe snel er geknipt wordt, het soort beelden wat een goed shot
            is. Wisselen is gratis: er wordt nog niets gerenderd.
          </p>
          <div className="segment">
            <button
              aria-pressed={tab === "montage"}
              onClick={() => setTab("montage")}
            >
              Montage · {stijlen?.montagestijlen.length ?? 0}
            </button>
            <button
              aria-pressed={tab === "titels"}
              onClick={() => setTab("titels")}
            >
              Titels · {stijlen?.titelstijlen.length ?? 0}
            </button>
            <button
              aria-pressed={tab === "beelden"}
              onClick={() => setTab("beelden")}
            >
              Soort beelden · {stijlen?.stijlen.length ?? 0}
            </button>
          </div>
          {tab === "montage" && (
            <div className="chip-rij">
              {BANDEN.map((b) => (
                <button
                  key={b.sleutel}
                  className="chip-knop"
                  aria-pressed={band === b.sleutel}
                  onClick={() => setBand(b.sleutel)}
                >
                  {b.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {stijlen === null && fout === null && <div className="lijst-leeg">Stijlen ophalen…</div>}

        {tab === "montage" ? (
          <div className="stijl-lijst">
            {zichtbaar.map((m) => (
              <MontageKaart
                key={m.id}
                m={m}
                gekozen={m.id === keuze.montage}
                voorstel={stijlen?.montage_herkend === m.id}
                onKies={() => setKeuze({ ...keuze, montage: m.id })}
              />
            ))}
            {stijlen !== null && zichtbaar.length === 0 && (
              <div className="lijst-leeg">Geen montagestijl in deze band.</div>
            )}
          </div>
        ) : tab === "titels" ? (
          <div className="titel-raster">
            {titelbezig && (
              <div className="lijst-leeg titel-melding">
                Voorbeeldbeelden maken… elk beeld is een echt frame uit de render.
              </div>
            )}
            {(titelbeelden ?? stijlen?.titelstijlen ?? []).map((ts) => (
              <TitelKaart
                key={ts.id}
                ts={ts}
                gekozen={ts.id === (keuze.titel || stijlen?.titel_gekozen)}
                onKies={() => setKeuze({ ...keuze, titel: ts.id })}
              />
            ))}
          </div>
        ) : (
          <div className="stijl-lijst">
            {stijlen?.stijlen.map((s) => (
              <button
                key={s.naam}
                className="stijl-kaart"
                aria-pressed={s.naam === keuze.stijl}
                onClick={() => setKeuze({ ...keuze, stijl: s.naam })}
              >
                <span className="regel">
                  <b>{s.titel}</b>
                  {stijlen.herkend === s.naam && <span className="label-herkend">herkend</span>}
                </span>
                <span className="omschrijving">{s.omschrijving}</span>
              </button>
            ))}
          </div>
        )}

        {stijlen?.uitleg !== undefined && (
          <div className="voetnoot">
            <b>Wat BeatCut in je beelden ziet</b>
            <span>{stijlen.uitleg}</span>
          </div>
        )}
      </aside>

      <main className="podium">
        {fout !== null && (
          <div className="melding-fout" role="alert">
            <b>Dat ging niet goed</b>
            <span className="mono">{fout}</span>
            <button className="knop-klein" onClick={() => setFout(null)}>
              Sluiten
            </button>
          </div>
        )}

        <div className="samenvatting">
          <span className="kop-klein">Zo gaat BeatCut het monteren</span>
          <h2>{gekozenMontage?.titel ?? "Kies een montagestijl"}</h2>
          <div className="samenvatting-rijen">
            <div>
              <span>Snijritme</span>
              <b>{gekozenMontage?.snijritme ?? "—"}</b>
            </div>
            <div>
              <span>Soort beelden</span>
              <b>{gekozenStijl?.titel ?? "nog geen"}</b>
            </div>
            <div>
              <span>Titels</span>
              <b>{gekozenTitel?.naam ?? "nog geen"}</b>
            </div>
            <div>
              <span>Formaat</span>
              <b>
                {keuze.vorm}
                {gekozenVorm !== null && ` · ${gekozenVorm.breedte}×${gekozenVorm.hoogte}`}
              </b>
            </div>
            <div>
              <span>Lengte</span>
              <b>
                {lengte.label}
                {lengte.duur === null && muziek?.duur != null && ` · ${duurTekst(muziek.duur)}`}
              </b>
            </div>
            <div>
              <span>Muziek</span>
              <b title={muziek?.bestand}>{muziek === null ? "nog geen" : muziek.bestand}</b>
            </div>
          </div>
          {gekozenMontage !== null && (
            <p className="stap-uitleg">{gekozenMontage.omschrijving}</p>
          )}
          <p className="stap-uitleg">
            De voorvertoning die meteen meespeelt komt met de compositor. Tot die tijd maakt BeatCut
            de video echt: regie, render en nakijken, en dan speelt hij bij Exporteren.
          </p>
        </div>
      </main>

      <aside className="zijbalk rechts">
        <div className="groep">
          <div className="kop-klein">Formaat</div>
          <div className="vorm-raster">
            {stijlen?.vormen.map((v) => (
              <button
                key={v.naam}
                className="vorm-knop"
                aria-pressed={v.naam === keuze.vorm}
                onClick={() => setKeuze({ ...keuze, vorm: v.naam })}
              >
                <span className="vorm-vak">
                  <VormIcoon vorm={v} />
                </span>
                <span className="vorm-tekst">
                  <b>{v.naam}</b>
                  <span>
                    {v.breedte}×{v.hoogte}
                  </span>
                </span>
              </button>
            ))}
          </div>
          <span className="kleine-noot">
            Alleen hier te kiezen. De regisseur kadert elk shot op dit formaat, zodat je highlights
            in beeld blijven.
          </span>
        </div>

        <div className="groep">
          <div className="kop-klein">Lengte</div>
          <div className="chip-rij">
            {LENGTES.map((l) => (
              <button
                key={l.label}
                className="chip-knop"
                aria-pressed={l.duur === keuze.duur}
                onClick={() => setKeuze({ ...keuze, duur: l.duur })}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div className="groep">
          <div className="kop-klein">Muziek</div>
          <div className="muziek-kaart">
            <Noot />
            <span className="muziek-tekst">
              <b>{muziek?.bestand ?? "Nog geen muziek"}</b>
              <span>
                {muziek === null
                  ? "De snedes liggen op de beat, dus zonder muziek is er geen ritme."
                  : meet
                    ? "BPM wordt gemeten…"
                    : `${muziek.bpm != null ? `${Math.round(muziek.bpm)} BPM` : "BPM onbekend"}${
                        muziek.duur != null ? ` · ${duurTekst(muziek.duur)}` : ""
                      }`}
              </span>
            </span>
          </div>

          <div className="segment">
            {BRONNEN.map((b) => (
              <button
                key={b.sleutel}
                aria-pressed={bron === b.sleutel}
                onClick={() => setBron(b.sleutel)}
              >
                {b.label}
              </button>
            ))}
          </div>

          {bron === "eigen" && (
            <button className="knop" onClick={() => void kiesMuziek()}>
              Kies muziek…
            </button>
          )}

          {bron === "gen" && muziekmodel?.aanwezig === false && (
            <div className="muziek-kaart kolom">
              <b>Muziek maken op deze computer</b>
              <span className="kleine-noot">
                Eenmalig ongeveer 11 GB downloaden. Daarna werkt het zonder internet en is
                alles wat je maakt vrij te gebruiken, zonder naamsvermelding. Hoe lang het
                duurt hangt van je verbinding af: op een snelle lijn een paar minuten, op
                een trage een half uur of langer. Je kunt ondertussen doorwerken.
              </span>
              {installeert ? (
                <>
                  <div className="balk-tekst breed">
                    <div className="regel">
                      <span className="stap-naam">{instStand.tekst || "Bezig…"}</span>
                      <span className="detail">{instStand.percentage}%</span>
                    </div>
                    <div className="voortgangsbalk">
                      <div
                        className="vulling"
                        style={{ "--deel": instStand.percentage / 100 } as CSSProperties}
                      />
                    </div>
                  </div>
                  {instStand.totaal > 0 && (
                    <span className="kleine-noot">
                      {bytesTekst(instStand.gedaan)} van {bytesTekst(instStand.totaal)}
                    </span>
                  )}
                  <button className="knop" onClick={() => void stopInstallatie()}>
                    Annuleren
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="knop-primair"
                    onClick={() => void installeerModel()}
                    disabled={!online}
                  >
                    Installeren
                  </button>
                  {!online && (
                    <span className="kleine-noot">
                      Zet de schakelaar rechtsboven op Online: het model moet één keer van
                      internet komen. Kies tot die tijd een eigen nummer.
                    </span>
                  )}
                </>
              )}
              {instFout !== null && (
                <span className="noot-waarschuwing" role="alert">
                  {instFout}
                </span>
              )}
            </div>
          )}

          {bron === "gen" && muziekmodel?.aanwezig && (
            <>
              <span className="kleine-noot">
                Gemaakt op deze computer, op het tempo dat bij je stijl past. Vrij te
                gebruiken, geen naamsvermelding.
              </span>
              <div className="chip-rij">
                {muziekmodel.genres.map((g) => (
                  <button
                    key={g.naam}
                    className="chip-knop"
                    aria-pressed={genre === g.naam}
                    onClick={() => setGenre(g.naam)}
                  >
                    {g.naam}
                  </button>
                ))}
              </div>
              <button
                className="schakelaar"
                role="switch"
                aria-checked={zang}
                onClick={() => setZang((z) => !z)}
              >
                <span>Met zang</span>
                <span className="wip" />
              </button>
              {componeert ? (
                <div className="balk-tekst breed">
                  <div className="regel">
                    <span className="stap-naam">{genVoortgang.tekst || "Componeren…"}</span>
                    <span className="detail">{genVoortgang.percentage}%</span>
                  </div>
                  <div className="voortgangsbalk">
                    <div
                      className="vulling"
                      style={{ "--deel": genVoortgang.percentage / 100 } as CSSProperties}
                    />
                  </div>
                </div>
              ) : (
                <button className="knop" onClick={() => void componeer()}>
                  Genereer {VARIANTEN} varianten
                </button>
              )}
              {varianten.map((v) => (
                <div key={v.pad} className="variant">
                  <button
                    className="speelknop"
                    aria-pressed={speelt === v.pad}
                    aria-label={speelt === v.pad ? "Pauzeer" : "Speel af"}
                    onClick={() => speelAfOfStop(v)}
                  >
                    {speelt === v.pad ? "❙❙" : "▶"}
                  </button>
                  <span className="muziek-tekst">
                    <b>
                      Variant {v.variant}
                      {v.zang ? " · met zang" : ""}
                    </b>
                    <span>
                      {v.genre} · {bpmTekst(v)} · {duurTekst(v.duur)}
                    </span>
                  </span>
                  <button className="knop klein" onClick={() => void gebruikVariant(v)}>
                    Gebruik deze
                  </button>
                </div>
              ))}
              {/* Eén speler voor alle varianten. `asset:`-adres, dus het
                  asset-protocol moet de projectmap mogen lezen (lib.rs). */}
              <audio ref={speler} onEnded={() => setSpeelt(null)} preload="none" hidden />
            </>
          )}
        </div>

        <div className="afsluiter">
          {muziek === null && (
            <span className="kleine-noot">
              Kies eerst een muziekstuk. BeatCut legt elke snede op een tel, dus zonder muziek is er
              niets om op te monteren.
            </span>
          )}
          <button className="knop-groot vol" onClick={onMaakVideo} disabled={!kanDoor}>
            Maak video →
          </button>
        </div>
      </aside>
    </div>
  );
}

/** Eén montagestijl: energiebalkjes, naam, snijritme en wat hij doet. */
function MontageKaart({
  m,
  gekozen,
  voorstel,
  onKies,
}: {
  m: Montagestijl;
  gekozen: boolean;
  voorstel: boolean;
  onKies: () => void;
}) {
  return (
    <button className="stijl-kaart met-energie" aria-pressed={gekozen} onClick={onKies}>
      <Energie energie={m.energie} />
      <span className="montage-tekst">
        <span className="regel">
          <b>{m.titel}</b>
          <span className="snijritme mono">{m.snijritme}</span>
        </span>
        <span className="omschrijving">{m.omschrijving}</span>
        {voorstel && <span className="label-herkend">past bij je beelden</span>}
      </span>
    </button>
  );
}

/** Eén titelstijl. Het beeld is een echt frame uit dezelfde compositie die
 *  straks over de video komt — geen nagemaakte kaart. Zolang het er niet is
 *  staat er de naam van de stijl in zijn plaats, zodat de kaart niet leeg is. */
function TitelKaart({
  ts,
  gekozen,
  onKies,
}: {
  ts: Titelstijl;
  gekozen: boolean;
  onKies: () => void;
}) {
  return (
    <button className="titel-kaart" aria-pressed={gekozen} onClick={onKies}>
      <span className="titel-beeld">
        {ts.voorbeeld === null ? (
          <span className="titel-wacht">{ts.naam}</span>
        ) : (
          <img src={convertFileSrc(ts.voorbeeld)} alt={`Voorbeeld van ${ts.naam}`} />
        )}
      </span>
      <span className="titel-tekst">
        <b>{ts.naam}</b>
        <span className="omschrijving">{ts.animatie}</span>
      </span>
    </button>
  );
}

function Noot() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="noot">
      <path d="M7 14V4l8-2v10" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="5" cy="14" r="2" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
      <circle cx="13" cy="12" r="2" fill="none" stroke="var(--accent)" strokeWidth="1.6" />
    </svg>
  );
}

/** Wat er aan tempo te melden valt: gevraagd, en wat er écht uit kwam.
 *
 *  ACE-Step haalt het gevraagde tempo niet altijd; de engine meet daarom na en
 *  probeert het bij meer dan 3 BPM afwijking opnieuw met een andere seed. Wat
 *  er dan nog overblijft hoort de gebruiker te zien — hij kiest erop. */
function bpmTekst(v: MuziekVariant): string {
  if (v.bpm_gemeten == null) return `${v.bpm} BPM gevraagd`;
  const gemeten = Math.round(v.bpm_gemeten);
  if (v.bpm_afwijking != null && v.bpm_afwijking <= 1) return `${gemeten} BPM`;
  return `${gemeten} BPM gemeten · ${v.bpm} gevraagd`;
}
