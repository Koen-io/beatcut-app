import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import Media from "./Media";
import Stijl, { type Keuze } from "./Stijl";
import Look from "./Look";
import Bijwerken from "./Bijwerken";
import Exporteren, { type Kwaliteit, type MontageStand } from "./Exporteren";
import { useBijwerken } from "./zelf-bijwerken";
import { useOnderdelen } from "./onderdelen";
import {
  GEBEURTENIS,
  doctor,
  engine,
  hallo,
  projectMaakVideo,
  webgpuCheck,
  type Check,
  type Doctor,
  type EngineGebeurtenis,
  type Hallo,
  type Montage,
} from "./engine";

const STAPPEN = [
  { id: "media", label: "Media" },
  { id: "stijl", label: "Stijl" },
  { id: "look", label: "Look" },
  { id: "bijwerken", label: "Bijwerken" },
  { id: "exporteren", label: "Exporteren" },
] as const;
type StapId = (typeof STAPPEN)[number]["id"];

const BEGINKEUZE: Keuze = { stijl: "", montage: "", titel: "", vorm: "16:9", duur: null };

// Alleen macOS legt de verkeerslichten óver de pagina heen (`titleBarStyle:
// "Overlay"` in tauri.conf.json); daar moet links 84 px vrij blijven. Windows
// en Linux houden hun eigen titelbalk bóven de webview (`decorations` staat
// aan), dus daar overlapt niets en hoort er ook geen ruimte gereserveerd te
// worden — gecontroleerd 03-10-2026 met een Windows-userAgent.
const isMac = navigator.userAgent.includes("Mac");

// Online of offline blijft bewaard tussen starts; standaard online.
const ONLINE_SLEUTEL = "beatcut.online";
function onlineUitOpslag(): boolean {
  return localStorage.getItem(ONLINE_SLEUTEL) !== "nee";
}

type EngineStand =
  | { soort: "laden" }
  | { soort: "klaar"; hallo: Hallo; doctor: Doctor }
  | { soort: "fout"; bericht: string };

export default function App() {
  const [stap, setStap] = useState<StapId>("media");
  // Welke stappen de gebruiker geopend heeft gehad. Een vinkje op de
  // stappenbalk hoort te betekenen "dit heb ik gedaan", niet "deze staat links
  // van waar ik nu ben": wie van Stijl rechtstreeks naar Exporteren springt
  // heeft Look en Bijwerken niet gezien en hoort daar geen vinkje te krijgen.
  const [bezocht, setBezocht] = useState<Set<StapId>>(() => new Set(["media"]));
  const [stand, setStand] = useState<EngineStand>({ soort: "laden" });
  const [gekozen, setGekozen] = useState<string | null>(null);
  const [paneel, setPaneel] = useState(false);
  const [licenties, setLicenties] = useState<string | null>(null);
  const [titelpaneel, setTitelpaneel] = useState(false);
  const [webgpu, setWebgpu] = useState<Check | null>(null);
  const [keuze, setKeuze] = useState<Keuze>(BEGINKEUZE);
  const [montage, setMontage] = useState<MontageStand>(null);
  const [online, setOnline] = useState(onlineUitOpslag);

  // Een render mag nooit door een herstart afgebroken worden. Of er werk
  // loopt vraagt de haak zelf aan de engine — die weet het ook van een
  // project waar dit scherm net niet naar kijkt.
  const bijwerken = useBijwerken(online);

  // De titels in de export worden door een browser getekend, en die zit niet
  // in de installer. Ontbreekt hij en is er internet, dan haalt de haak hem
  // op de achtergrond op; de chip hieronder is het enige dat je ervan merkt.
  const onderdelen = useOnderdelen(online);

  function zetOnline(aan: boolean) {
    localStorage.setItem(ONLINE_SLEUTEL, aan ? "ja" : "nee");
    setOnline(aan);
  }

  // De listener hangt er één keer en moet weten welk project nú open staat.
  const projectRef = useRef<string | null>(gekozen);
  projectRef.current = gekozen;

  useEffect(() => {
    (async () => {
      try {
        const [h, d] = await Promise.all([hallo(), doctor()]);
        setStand({ soort: "klaar", hallo: h, doctor: d });
      } catch (e) {
        setStand({ soort: "fout", bericht: String(e) });
      }
      setWebgpu(await webgpuCheck());
    })();
  }, []);

  // De montage loopt door terwijl de gebruiker van stap wisselt, dus de stand
  // hoort hier en niet in Exporteren: anders mist dat scherm de eerste
  // meldingen omdat het nog niet getekend was toen ze binnenkwamen.
  useEffect(() => {
    const stop = listen<EngineGebeurtenis>(GEBEURTENIS, ({ payload }) => {
      if (payload.data.werk !== "maakvideo") return;
      if (payload.data.project !== projectRef.current) return;
      if (payload.gebeurtenis === "voortgang") {
        setMontage((m) => ({
          soort: "bezig",
          kwaliteit: m?.soort === "bezig" ? m.kwaliteit : "preview",
          voortgang: payload.data,
        }));
      } else if (payload.gebeurtenis === "fout") {
        setMontage({ soort: "fout", bericht: payload.data.fout });
      } else {
        setMontage({ soort: "klaar", montage: payload.data as Montage });
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, []);

  /** Regie + render + nakijken starten. Eén plek, want Stijl doet het met
   *  "preview" en Exporteren met "eind".
   *
   *  Wie wél en niet opnieuw regisseert, beslist de engine: alleen een andere
   *  stijl, vorm of lengte dan waarmee `edl.json` bedacht is leidt tot een
   *  verse regie. Dat hoort daar en niet hier — de interface hield het eerst
   *  zelf bij en vergat het, en dan gooide "Exporteer op volle kwaliteit" al
   *  het handwerk uit stap 4 weg. Alleen stap 4 zelf stuurt `false` mee. */
  async function startMontage(kwaliteit: Kwaliteit, regie?: boolean) {
    if (gekozen === null || keuze.stijl === "") return;
    setMontage({ soort: "bezig", kwaliteit, voortgang: null });
    try {
      await projectMaakVideo(
        gekozen, keuze.stijl, keuze.montage, keuze.titel,
        keuze.vorm, keuze.duur, kwaliteit, regie,
      );
    } catch (e) {
      setMontage({ soort: "fout", bericht: String(e) });
    }
  }

  /** Een ander project betekent een andere montage, een andere video en een
   *  andere voortgang. Bleef die stand staan, dan wees de speler in Exporteren
   *  naar de render van het vorige project onder de naam van het nieuwe. */
  function kiesProject(naam: string | null) {
    setGekozen((vorig) => {
      if (vorig !== naam) setMontage(null);
      return naam;
    });
  }

  /** Elke stapwissel loopt hierlangs, zodat `bezocht` niet achterloopt. */
  function ga(naar: StapId) {
    setBezocht((b) => (b.has(stap) ? b : new Set(b).add(stap)));
    setStap(naar);
  }

  /** Een stap is pas klaar als hij geopend is geweest én zijn eigen uitkomst
   *  er ligt. Look en Bijwerken hebben geen harde uitkomst — daar is "geweest
   *  en weer weg" het enige eerlijke antwoord. */
  function isKlaar(id: StapId): boolean {
    if (id === stap || !bezocht.has(id)) return false;
    if (id === "media") return gekozen !== null;
    if (id === "stijl") return keuze.stijl !== "";
    if (id === "exporteren") return montage?.soort === "klaar";
    return true;
  }

  const engineOk = stand.soort === "klaar" && stand.doctor.ok;

  return (
    <div className="app">
      <header className={`titelbalk${isMac ? " mac" : ""}`} data-tauri-drag-region>
        <div className="links" data-tauri-drag-region>
          <Logo />
          <div className="project-naam" data-tauri-drag-region>
            <b>{gekozen ?? "BeatCut"}</b>
            <span>montage altijd lokaal</span>
          </div>
        </div>

        <nav className="stappen" aria-label="Stappen">
          {STAPPEN.map((s, i) => (
            <button
              key={s.id}
              className={`stap${isKlaar(s.id) ? " klaar" : ""}`}
              aria-current={s.id === stap ? "step" : undefined}
              onClick={() => ga(s.id)}
            >
              <span className="nr">{isKlaar(s.id) ? "✓" : i + 1}</span>
              {s.label}
            </button>
          ))}
        </nav>

        <div className="rechts">
          <button
            className="schakelaar-online"
            role="switch"
            aria-checked={online}
            aria-label="Online werken"
            onClick={() => zetOnline(!online)}
          >
            <span className="spoor"><span className="knopje" /></span>
            {online ? "Online" : "Offline"}
          </button>
          {onderdelen.chip !== null && (
            <button
              className="chip"
              onClick={() => setTitelpaneel((p) => !p)}
              aria-expanded={titelpaneel}
              title={onderdelen.chipUitleg}
            >
              <span
                className={`dot ${
                  onderdelen.stand.soort === "fout"
                    ? "fout"
                    : onderdelen.stand.soort === "bezig"
                      ? "bezig"
                      : ""
                }`}
              />
              {onderdelen.chip}
            </button>
          )}
          <button className="chip" onClick={() => setPaneel((p) => !p)} aria-expanded={paneel}>
            <span className={`dot ${stand.soort === "laden" ? "" : engineOk ? "ok" : "fout"}`} />
            {stand.soort === "laden" ? "Engine start…" : engineOk ? `Engine ${stand.hallo.versie}` : "Engine: aandacht nodig"}
          </button>
          <button
            className="knop-primair"
            onClick={() => ga("exporteren")}
            disabled={gekozen === null}
            title={gekozen === null ? "Voeg eerst clips toe" : undefined}
          >
            Exporteren
          </button>
        </div>
      </header>

      {stap === "media" ? (
        <Media naarStijl={() => ga("stijl")} onProject={kiesProject} />
      ) : stap === "stijl" ? (
        <Stijl
          project={gekozen}
          keuze={keuze}
          setKeuze={setKeuze}
          online={online}
          onMaakVideo={() => {
            void startMontage("preview");
            ga("exporteren");
          }}
        />
      ) : stap === "look" ? (
        <Look project={gekozen} naarExporteren={() => ga("exporteren")} />
      ) : stap === "bijwerken" ? (
        <Bijwerken
          project={gekozen}
          keuze={keuze}
          naarStijl={() => ga("stijl")}
          onMaakVideo={() => {
            void startMontage("preview", false);
            ga("exporteren");
          }}
        />
      ) : (
        <Exporteren
          project={gekozen}
          keuze={keuze}
          stand={montage}
          onderdelen={onderdelen}
          naarStijl={() => ga("stijl")}
          onVolleKwaliteit={() => void startMontage("eind")}
        />
      )}

      {bijwerken.zichtbaar && bijwerken.stand.soort === "klaar" && (
        <div className="melding-update" role="status">
          <div className="kop">
            <span className="teken">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <path d="M7 2v7M4 6.5L7 9.5l3-3M2.5 12h9" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <b>BeatCut {bijwerken.stand.versie} staat klaar</b>
              <span>
                {bijwerken.magHerstarten
                  ? "Op de achtergrond opgehaald, handtekening gecontroleerd. Hij wordt pas geïnstalleerd als je herstart."
                  : `Op de achtergrond opgehaald. Er loopt nog werk (${bijwerken.bezigMet}) — herstarten kan zodra dat klaar is.`}
              </span>
            </div>
          </div>
          <div className="knoppen">
            <button className="knop" onClick={bijwerken.verberg}>Bij afsluiten</button>
            <button
              className="knop-licht"
              onClick={() => void bijwerken.herstart()}
              disabled={!bijwerken.magHerstarten}
              title={bijwerken.magHerstarten ? undefined : `Nu niet: ${bijwerken.bezigMet}`}
            >
              Nu herstarten
            </button>
          </div>
        </div>
      )}

      {titelpaneel && (
        <div className="paneel" role="dialog" aria-label="Titels in de export">
          <h2>Titels in de export</h2>
          <p className="paneel-uitleg">
            {onderdelen.status?.uitleg ??
              "De titels in de export worden door een browser getekend."}
            {!online && " Je staat op Offline, dus BeatCut haalt nu niets op."}
          </p>
          {onderdelen.stand.soort === "fout" && (
            <p className="mono">{onderdelen.stand.bericht}</p>
          )}
          {(onderdelen.status?.onderdelen ?? []).map((o) => (
            <div className="check" key={o.naam}>
              <span className={`dot ${o.aanwezig ? "ok" : ""}`} style={{ marginTop: 5 }} />
              <span>{o.titel}</span>
              <span className="detail" title={o.pad ?? ""}>
                {o.aanwezig ? o.versie : "nog niet klaargezet"}
              </span>
            </div>
          ))}
          <div className="paneel-knoppen">
            {onderdelen.stand.soort === "bezig" ? (
              <button className="knop" onClick={() => void onderdelen.stop()}>
                Stoppen
              </button>
            ) : (
              <button
                className="knop-licht"
                disabled={!online}
                title={online ? undefined : "Zet Online aan om dit op te halen"}
                onClick={() => void onderdelen.start()}
              >
                {onderdelen.stand.soort === "fout" ? "Opnieuw proberen" : "Nu ophalen"}
              </button>
            )}
          </div>
        </div>
      )}

      {paneel && (
        <div className="paneel" role="dialog" aria-label="Engine">
          {stand.soort === "laden" && <p>De engine wordt gestart…</p>}
          {stand.soort === "fout" && (
            <>
              <h2>Engine niet bereikbaar</h2>
              <p className="mono">{stand.bericht}</p>
            </>
          )}
          {stand.soort === "klaar" && (
            <>
              <h2>
                Engine {stand.hallo.versie} · protocol {stand.hallo.protocol} · {stand.doctor.ok ? "alles in orde" : `${stand.doctor.fouten} probleem/problemen`}
              </h2>
              {[...stand.doctor.checks, ...(webgpu ? [webgpu] : [])].map((c) => (
                <div className="check" key={c.naam}>
                  <span className={`dot ${c.ok ? "ok" : c.vereist ? "fout" : ""}`} style={{ marginTop: 5 }} />
                  <span>{c.naam}</span>
                  <span className="detail" title={c.detail}>{c.detail}</span>
                </div>
              ))}
              <button
                className="knop-klein"
                style={{ marginTop: 12 }}
                onClick={() => {
                  if (licenties !== null) return setLicenties(null);
                  engine<{ tekst: string }>("licenties")
                    .then((r) => setLicenties(r.tekst))
                    .catch((e) => setLicenties(String(e)));
                }}
              >
                {licenties === null ? "Licenties van derden" : "Licenties verbergen"}
              </button>
              {licenties !== null && <pre className="licenties">{licenties}</pre>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Logo() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="#16191F" />
      <rect x="5" y="10" width="2" height="4" rx="1" fill="var(--accent)" />
      <rect x="8.5" y="7" width="2" height="10" rx="1" fill="var(--accent)" />
      <rect x="12" y="5" width="2" height="14" rx="1" fill="#F3F4F6" />
      <rect x="15.5" y="8" width="2" height="8" rx="1" fill="var(--accent)" />
      <rect x="19" y="10.5" width="2" height="3" rx="1" fill="var(--accent)" />
    </svg>
  );
}
