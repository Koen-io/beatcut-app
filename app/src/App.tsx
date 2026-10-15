import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { ask } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { neemNaAfloop, onthoudNaAfloop } from "./exportgeheugen";
import Media from "./Media";
import Stijl, { type Keuze } from "./Stijl";
import Look from "./Look";
import Bijwerken from "./Bijwerken";
import Exporteren, { type Kwaliteit, type MontageStand } from "./Exporteren";
import { useBijwerken } from "./zelf-bijwerken";
import BijwerkDialoog from "./BijwerkDialoog";
import Instellingen, { type EngineStand } from "./Instellingen";
import { EDITIE, LOGO_URL } from "./editie";
import pakket from "../package.json";

/** De versie van de app zelf; release.sh houdt hem gelijk aan die van de engine. */
const APP_VERSIE: string = pakket.version;
import { useOnderdelen } from "./onderdelen";
import Splash, { useSplash, type SplashStand } from "./Splash";
import {
  GEBEURTENIS,
  doctor,
  hallo,
  muziekInstalleer,
  muziekStatus,
  projectMaakVideo,
  projectStijlen,
  projectVoorbereid,
  webgpuCheck,
  type Check,
  type EngineGebeurtenis,
  type Exportkeuze,
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
  const [titelpaneel, setTitelpaneel] = useState(false);
  const [webgpu, setWebgpu] = useState<Check | null>(null);
  const [keuze, setKeuze] = useState<Keuze>(BEGINKEUZE);
  const [montage, setMontage] = useState<MontageStand>(null);
  const [online, setOnline] = useState(onlineUitOpslag);
  // Eerste start: de onderdelen voor de titels in de export worden opgehaald.
  // Zolang dat op de splash staat wacht de app erop — tenzij de gebruiker
  // "Overslaan en beginnen" kiest, en dan loopt het op de achtergrond door.
  const [wachtOpOnderdelen, setWachtOpOnderdelen] = useState(false);
  const [muziekAchtergrond, setMuziekAchtergrond] = useState(false);

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

  /** Het muziekmodel op de achtergrond ophalen — Koens keuze: BeatCut start
   *  alvast, en muziek genereren wordt beschikbaar zodra het model binnen is.
   *  Elf gigabyte is niets om een eerste start op te laten wachten, en wie het
   *  nooit gebruikt hoeft er nooit iets van te merken. De stand staat in stap 2
   *  bij Muziek; hier gaat alleen de download aan. */
  useEffect(() => {
    if (!online || stand.soort !== "klaar") return;
    let gestopt = false;
    (async () => {
      try {
        const m = await muziekStatus();
        if (gestopt || m.aanwezig) return;
        if (m.installeren_bezig === true) {
          setMuziekAchtergrond(true);
          return;
        }
        await muziekInstalleer();
        if (!gestopt) setMuziekAchtergrond(true);
      } catch {
        // Geen model en geen download is geen reden om de start te verstoren;
        // de kaart in stap 2 vertelt het verhaal wel als iemand muziek wil.
      }
    })();
    return () => {
      gestopt = true;
    };
  }, [online, stand.soort]);

  /** Wacht de splash op de onderdelen voor de titels? Alleen bij een verse
   *  installatie, en alleen zolang ze echt binnenkomen: zonder internet of na
   *  een mislukking heeft wachten geen zin. */
  useEffect(() => {
    if (onderdelen.stand.soort === "bezig") setWachtOpOnderdelen(true);
    if (onderdelen.stand.soort === "klaar") setWachtOpOnderdelen(false);
  }, [onderdelen.stand.soort]);

  const engineKlaar = stand.soort !== "laden";
  const splashStand: SplashStand =
    stand.soort === "fout"
      ? { soort: "fout", bericht: stand.bericht }
      : wachtOpOnderdelen
        ? {
            soort: "installeren",
            onderdelen: onderdelen.stand,
            bytes: onderdelen.status?.bytes ?? 0,
            nodig: onderdelen.status?.nodig_bytes ?? 0,
          }
        : { soort: "starten" };
  // De splash verdwijnt zodra de engine antwoordt. Een fout houdt hem vast:
  // doorgaan naar een leeg scherm vertelt niemand wat er aan de hand is.
  const splash = useSplash(engineKlaar && !wachtOpOnderdelen && stand.soort !== "fout");

  // Zelf bijwerken: zodra de splash weg is één keer kijken, daarna elke vier
  // uur, en op de knop in de instellingen. Een render mag nooit door een
  // herstart afgebroken worden: of er werk loopt vraagt de haak zelf aan de
  // engine — die weet het ook van een project waar dit scherm niet naar kijkt.
  const bijwerken = useBijwerken(online, !splash.zichtbaar);

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
        const klaar = payload.data as Montage;
        setMontage({ soort: "klaar", montage: klaar });
        // "Toon in Finder als het klaar is": hier, niet in Exporteren — dat
        // paneel is er niet als je intussen naar een andere stap klikte.
        const wens = neemNaAfloop(klaar.project);
        if (wens?.toon) {
          revealItemInDir(klaar.export?.pad ?? klaar.video).catch(() => {});
        }
      }
    });
    return () => {
      void stop.then((f) => f());
    };
  }, []);

  // Afsluiten terwijl er gerenderd wordt: eerst vragen. Zonder dit verdween
  // een render van tien minuten met één Cmd+Q, zonder een woord.
  const renderBezig = montage?.soort === "bezig";
  useEffect(() => {
    if (!renderBezig) return;
    const venster = getCurrentWindow();
    const stop = venster.onCloseRequested(async (e) => {
      const toch = await ask(
        `${EDITIE.naam} is nog bezig met je video. Als je nu afsluit gaat die verloren.`,
        { title: "Video nog niet klaar", kind: "warning", okLabel: "Toch afsluiten", cancelLabel: "Doorgaan" },
      );
      if (!toch) e.preventDefault();
    });
    return () => {
      void stop.then((f) => f());
    };
  }, [renderBezig]);

  /** Regie + render + nakijken starten. Eén plek, want Stijl doet het met
   *  "preview" en Exporteren met "eind".
   *
   *  Wie wél en niet opnieuw regisseert, beslist de engine: alleen een andere
   *  stijl, vorm of lengte dan waarmee `edl.json` bedacht is leidt tot een
   *  verse regie. Dat hoort daar en niet hier — de interface hield het eerst
   *  zelf bij en vergat het, en dan gooide "Exporteer op volle kwaliteit" al
   *  het handwerk uit stap 4 weg. Alleen stap 4 zelf stuurt `false` mee. */
  async function startMontage(kwaliteit: Kwaliteit, regie?: boolean, exportkeuze?: Exportkeuze) {
    if (gekozen === null) return;
    if (keuze.stijl === "") {
      // Niet stil terugkeren: de gebruiker heeft op een knop gedrukt en staat
      // al op Exporteren te wachten op een video die nooit komt.
      setMontage({
        soort: "fout",
        bericht: `Kies eerst bij Stijl wat voor video het wordt; daarna kan ${EDITIE.naam} hem maken.`,
      });
      return;
    }
    setMontage({ soort: "bezig", kwaliteit, voortgang: null });
    try {
      await projectMaakVideo(
        gekozen, keuze.stijl, keuze.montage, keuze.titel,
        keuze.vorm, keuze.duur, kwaliteit, regie, exportkeuze,
      );
    } catch (e) {
      setMontage({ soort: "fout", bericht: String(e) });
    }
  }

  /** De gewone weg uit Stijl: de montage bedenken (zonder te renderen) en door
   *  naar Look. Look en Bijwerken hebben een montage nodig om iets te laten
   *  zien; de engine bedenkt hem alleen opnieuw als de keuzes veranderd zijn,
   *  dus heen en weer lopen gooit geen handwerk weg. Fouten gaan terug naar
   *  Stijl, die ze toont. */
  async function naarLook() {
    if (gekozen === null || keuze.stijl === "") return;
    await projectVoorbereid(
      gekozen, keuze.stijl, keuze.montage, keuze.titel, keuze.vorm, keuze.duur,
    );
    ga("look");
  }

  /** Een ander project betekent een andere montage, een andere video en een
   *  andere voortgang. Bleef die stand staan, dan wees de speler in Exporteren
   *  naar de render van het vorige project onder de naam van het nieuwe. */
  const kiesProject = useCallback((naam: string | null) => {
    // Vast adres: Media heeft deze functie in een effect staan, en een nieuwe
    // functie bij elke hertekening van App (elke voortgangsmelding!) liet dat
    // scherm zichzelf steeds leegmaken en zijn clips opnieuw ophalen.
    setGekozen((vorig) => {
      if (vorig !== naam) {
        setMontage(null);
        // De keuzes uit Stijl horen bij één project.
        setKeuze(BEGINKEUZE);
      }
      return naam;
    });
  }, []);

  // Een project met een montage begint met de keuzes waarmee die bedacht is.
  // Zonder dit stond er na een herstart 16:9 en "automatische lengte", zag de
  // engine dat als een nieuwe keuze en regisseerde hij opnieuw — dwars over
  // het handwerk uit Bijwerken heen. Ook wie Stijl overslaat en meteen naar
  // Exporteren gaat heeft zo een geldige keuze.
  useEffect(() => {
    if (gekozen === null) return;
    let geldig = true;
    projectStijlen(gekozen)
      .then((s) => {
        if (!geldig || s.brief === null) return;
        const brief = s.brief;
        setKeuze((k) =>
          k.stijl !== ""
            ? k // er is in deze sessie al gekozen; dat gaat voor
            : { stijl: brief.stijl, montage: brief.montage, titel: s.titel_gekozen,
                vorm: brief.vorm, duur: brief.duur },
        );
      })
      .catch(() => {
        // Geen brief is geen fout: Stijl vraagt het straks zelf en toont dan
        // wat er misging.
      });
    return () => {
      geldig = false;
    };
  }, [gekozen]);

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
      {splash.zichtbaar && (
          <Splash
            stand={splashStand}
            uit={splash.uit}
            muziekOpDeAchtergrond={muziekAchtergrond}
            onOverslaan={wachtOpOnderdelen ? () => setWachtOpOnderdelen(false) : undefined}
          onOpnieuw={
            onderdelen.stand.soort === "fout" ? () => void onderdelen.start() : undefined
          }
        />
      )}
      <header className={`titelbalk${isMac ? " mac" : ""}`} data-tauri-drag-region>
        <div className="links" data-tauri-drag-region>
          <Logo />
          <div className="project-naam" data-tauri-drag-region>
            <b>{gekozen ?? EDITIE.naam}</b>
            <span>{EDITIE.regel}</span>
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
            className="knop-icoon"
            onClick={() => setPaneel((p) => !p)}
            aria-expanded={paneel}
            aria-label="Instellingen"
            title={
              bijwerken.fase.soort === "nieuw" || bijwerken.fase.soort === "klaar"
                ? `Instellingen — versie ${bijwerken.fase.controle.versie} beschikbaar`
                : "Instellingen"
            }
          >
            <Tandwiel nadruk={bijwerken.fase.soort === "nieuw" || bijwerken.fase.soort === "klaar"} />
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
          onVerder={naarLook}
          onMaakVideo={() => {
            void startMontage("preview");
            ga("exporteren");
          }}
        />
      ) : stap === "look" ? (
        <Look
          project={gekozen}
          naarBijwerken={() => ga("bijwerken")}
          onMaakVideo={() => {
            void startMontage("preview");
            ga("exporteren");
          }}
        />
      ) : stap === "bijwerken" ? (
        <Bijwerken
          project={gekozen}
          online={online}
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
          onFoutWeg={() => setMontage((m) => (m?.soort === "fout" ? null : m))}
          onVolleKwaliteit={(exportkeuze, toon) => {
            if (gekozen !== null) onthoudNaAfloop(gekozen, { toon });
            void startMontage("eind", undefined, exportkeuze);
          }}
        />
      )}

      <BijwerkDialoog b={bijwerken} />

      {titelpaneel && (
        <div className="paneel" role="dialog" aria-label="Titels in de export">
          <h2>Titels in de export</h2>
          <p className="paneel-uitleg">
            {onderdelen.status?.uitleg ??
              "De titels in de export worden door een browser getekend."}
            {!online && ` Je staat op Offline, dus ${EDITIE.naam} haalt nu niets op.`}
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
        <Instellingen
          b={bijwerken}
          stand={stand}
          webgpu={webgpu}
          online={online}
          versie={stand.soort === "klaar" ? stand.hallo.versie : APP_VERSIE}
        />
      )}
    </div>
  );
}

function Tandwiel({ nadruk }: { nadruk: boolean }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" style={{ position: "relative" }}>
      <path
        d="M6.7 1.5h2.6l.4 1.7a5 5 0 0 1 1.3.75l1.65-.55 1.3 2.25-1.3 1.15a5 5 0 0 1 0 1.5l1.3 1.15-1.3 2.25-1.65-.55a5 5 0 0 1-1.3.75l-.4 1.7H6.7l-.4-1.7a5 5 0 0 1-1.3-.75l-1.65.55-1.3-2.25 1.3-1.15a5 5 0 0 1 0-1.5L2.05 5.65l1.3-2.25 1.65.55a5 5 0 0 1 1.3-.75z"
        fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"
      />
      <circle cx="8" cy="8" r="1.8" fill="none" stroke="currentColor" strokeWidth="1.2" />
      {nadruk && <circle cx="13" cy="3" r="2.4" fill="var(--nadruk)" stroke="var(--chrome)" strokeWidth="1" />}
    </svg>
  );
}

function Logo() {
  if (LOGO_URL !== null) {
    return <img className="merk-logo" src={LOGO_URL} alt="" width={26} height={26} draggable={false} />;
  }
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
