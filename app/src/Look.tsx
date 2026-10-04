// Stap 3 — Look: kleur en sfeer over alle beelden.
// Ontwerp: ontwerp/beatcut2/Main.dc.html, scherm "3. LOOK".
//
// Anders dan bij Stijl staat hier wél een voorvertoning in het midden, en dat
// mag ook: het is geen nagemaakt beeld maar een echt frame uit dit project,
// door precies dezelfde keten als de export (`looks.voorbeeld()` →
// `render.voorbeeldfilter()` → de native compositor). Dezelfde LUT, dezelfde
// WGSL-shaders, hetzelfde framenummer.
import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  projectLookVoorbeeld,
  projectLookZet,
  projectLooks,
  type Afwerking,
  type LookInfo,
  type LookKeuze,
  type Looks,
} from "./engine";

/** De schuiven uit het ontwerp, in die volgorde. */
const SCHUIVEN: { sleutel: keyof Afwerking; label: string }[] = [
  { sleutel: "korrel", label: "Filmkorrel" },
  { sleutel: "halation", label: "Halation" },
  { sleutel: "gloed", label: "Gloed" },
  { sleutel: "vignet", label: "Vignet" },
  { sleutel: "lichtlek", label: "Lichtlek" },
];
/** De drie schakelaars. Aan is 1, uit is 0 — de engine rekent met 0..1. */
const SCHAKELAARS: { sleutel: keyof Afwerking; label: string }[] = [
  { sleutel: "breedbeeld", label: "Breedbeeldbalken" },
  { sleutel: "filmtrilling", label: "Filmtrilling" },
  { sleutel: "kleurrand", label: "Kleurrand" },
];

const LEEG: Afwerking = {
  korrel: 0, halation: 0, gloed: 0, vignet: 0,
  lichtlek: 0, breedbeeld: 0, filmtrilling: 0, kleurrand: 0,
};

const TEGEL_BREEDTE = 220;
const GROOT_BREEDTE = 960;
/** Hoeveel voorbeelden er tegelijk gemaakt mogen worden. Elk voorbeeld is een
 *  ffmpeg-aanroep; 24 tegelijk legt de machine plat en levert niets eerder op. */
const TEGELIJK = 3;
/** Wachttijd na de laatste schuifbeweging voor de grote voorvertoning ververst. */
const RUST_MS = 250;

const pct = (v: number) => Math.round(v * 100);

type Props = {
  project: string | null;
  /** Legt de keuze vast en gaat naar Exporteren. */
  naarExporteren: () => void;
};

export default function Look({ project, naarExporteren }: Props) {
  const [catalogus, setCatalogus] = useState<Looks | null>(null);
  const [keuze, setKeuze] = useState<LookKeuze | null>(null);
  const [sfeer, setSfeer] = useState("Alles");
  const [groot, setGroot] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [tegels, setTegels] = useState<Record<string, string>>({});
  const [fout, setFout] = useState<string | null>(null);

  useEffect(() => {
    if (project === null) return;
    setCatalogus(null);
    setKeuze(null);
    setTegels({});
    setGroot(null);
    projectLooks(project)
      .then((c) => {
        setCatalogus(c);
        setKeuze(c.gekozen);
      })
      .catch((e) => setFout(String(e)));
  }, [project]);

  // De grote voorvertoning. Debounce: aan een schuif draaien geeft tientallen
  // wijzigingen per seconde en elke voorvertoning is een ffmpeg-aanroep.
  useEffect(() => {
    if (project === null || keuze === null) return;
    let afgebroken = false;
    const t = setTimeout(() => {
      setBezig(true);
      projectLookVoorbeeld(project, keuze, GROOT_BREEDTE)
        .then((v) => {
          if (!afgebroken) setGroot(convertFileSrc(v.pad));
        })
        .catch((e) => {
          if (!afgebroken) setFout(String(e));
        })
        .finally(() => {
          if (!afgebroken) setBezig(false);
        });
    }, RUST_MS);
    return () => {
      afgebroken = true;
      clearTimeout(t);
    };
  }, [project, keuze]);

  /** Een tegel toont de look zelf: volle sterkte, met de afwerking die erbij
   *  hoort. Zo zie je waar je voor kiest, niet wat er nu toevallig ingesteld staat. */
  const tegelKeuze = useCallback(
    (look: LookInfo): LookKeuze => ({
      id: look.id,
      sterkte: 1,
      afwerking: { ...LEEG, ...look.afwerking },
    }),
    [],
  );

  // De tegels. Alleen wat zichtbaar is in het gekozen sfeerfilter, en met een
  // paar tegelijk — anders staan er 24 ffmpeg-processen om dezelfde schijf te
  // vechten en duurt de eerste tegel net zo lang als de laatste.
  const zichtbaar = (catalogus?.looks ?? []).filter(
    (l) => sfeer === "Alles" || l.sfeer === sfeer,
  );
  const zichtbaarIds = zichtbaar.map((l) => l.id).join(",");
  const tegelsRef = useRef(tegels);
  tegelsRef.current = tegels;

  useEffect(() => {
    if (project === null || zichtbaarIds === "") return;
    let afgebroken = false;
    const wachtrij = zichtbaarIds.split(",").filter((id) => !(id in tegelsRef.current));

    async function werker() {
      while (!afgebroken) {
        const id = wachtrij.shift();
        if (id === undefined) return;
        const look = (catalogus?.looks ?? []).find((l) => l.id === id);
        if (look === undefined) continue;
        try {
          const v = await projectLookVoorbeeld(project!, tegelKeuze(look), TEGEL_BREEDTE);
          if (!afgebroken) setTegels((t) => ({ ...t, [id]: convertFileSrc(v.pad) }));
        } catch {
          // Eén tegel die niet lukt mag de rest niet tegenhouden; de knop
          // werkt gewoon, er staat alleen geen beeld in.
        }
      }
    }
    void Promise.all(Array.from({ length: TEGELIJK }, werker));
    return () => {
      afgebroken = true;
    };
    // `catalogus` hoort hier niet in: die verandert alleen samen met het project.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, zichtbaarIds]);

  function kiesLook(look: LookInfo) {
    // Een nieuwe look brengt zijn eigen afwerkingsvoorstel mee — dat is het
    // halve werk van `looks.json`. De schakelaars blijven staan: die zijn een
    // keuze over het formaat, niet over de kleur.
    setKeuze((k) => ({
      id: look.id,
      sterkte: k?.sterkte ?? 1,
      afwerking: {
        ...LEEG,
        ...look.afwerking,
        breedbeeld: k?.afwerking.breedbeeld ?? 0,
        filmtrilling: k?.afwerking.filmtrilling ?? 0,
        kleurrand: k?.afwerking.kleurrand ?? 0,
      },
    }));
  }

  function zetAfwerking(sleutel: keyof Afwerking, waarde: number) {
    setKeuze((k) => (k === null ? k : { ...k, afwerking: { ...k.afwerking, [sleutel]: waarde } }));
  }

  async function verder() {
    if (project === null || keuze === null) return;
    try {
      await projectLookZet(project, keuze);
      naarExporteren();
    } catch (e) {
      setFout(String(e));
    }
  }

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

  const gekozenLook = catalogus?.looks.find((l) => l.id === keuze?.id) ?? null;

  return (
    <div className="werkvlak">
      <aside className="zijbalk breed look-lijst">
        <div className="groep">
          <h1 className="stap-titel">Look</h1>
          <p className="stap-uitleg">
            Kleur en sfeer over alle beelden. {Math.max(0, (catalogus?.looks.length ?? 1) - 1)}{" "}
            looks, elk met een eigen afwerking.
          </p>
        </div>

        <div className="chip-rij">
          {(catalogus?.sferen ?? []).map((s) => (
            <button
              key={s}
              className="chip-knop"
              aria-pressed={s === sfeer}
              onClick={() => setSfeer(s)}
            >
              {s}
            </button>
          ))}
        </div>

        {catalogus === null && fout === null && <div className="lijst-leeg">Looks ophalen…</div>}

        <div className="look-raster">
          {zichtbaar.map((l) => (
            <button
              key={l.id}
              className="look-tegel"
              aria-pressed={l.id === keuze?.id}
              onClick={() => kiesLook(l)}
            >
              <span className="beeld">
                {tegels[l.id] !== undefined ? (
                  <img src={tegels[l.id]} alt="" loading="lazy" />
                ) : (
                  <span className="balkje" />
                )}
              </span>
              <span className="naam">{l.naam}</span>
              <span className="sfeer">{l.sfeer || "Geen look"}</span>
            </button>
          ))}
        </div>
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

        <div className={`look-voorbeeld${bezig ? " bezig" : ""}`}>
          {groot !== null ? (
            <img src={groot} alt="Voorvertoning van de gekozen look" />
          ) : (
            <span className="lijst-leeg">Voorvertoning wordt gemaakt…</span>
          )}
        </div>
        <span className="kleine-noot">
          {gekozenLook?.naam ?? "Geen look"} · sterkte {pct(keuze?.sterkte ?? 1)}% · echt frame uit
          dit project, door dezelfde keten als de export
        </span>
      </main>

      <aside className="zijbalk rechts">
        <div className="groep">
          <div className="schuif-kop">
            <label htmlFor="fx-sterkte">Sterkte</label>
            <span className="mono">{pct(keuze?.sterkte ?? 1)}%</span>
          </div>
          <input
            id="fx-sterkte"
            type="range"
            min={0}
            max={100}
            value={pct(keuze?.sterkte ?? 1)}
            onChange={(e) =>
              setKeuze((k) => (k === null ? k : { ...k, sterkte: Number(e.target.value) / 100 }))
            }
          />
        </div>

        <div className="groep">
          <div className="kop-klein">Afwerking</div>
          {SCHUIVEN.map((s) => (
            <div key={s.sleutel} className="groep-schuif">
              <div className="schuif-kop">
                <label htmlFor={`fx-${s.sleutel}`}>{s.label}</label>
                <span className="mono">{pct(keuze?.afwerking[s.sleutel] ?? 0)}</span>
              </div>
              <input
                id={`fx-${s.sleutel}`}
                type="range"
                min={0}
                max={100}
                value={pct(keuze?.afwerking[s.sleutel] ?? 0)}
                onChange={(e) => zetAfwerking(s.sleutel, Number(e.target.value) / 100)}
              />
            </div>
          ))}
        </div>

        <div className="groep">
          {SCHAKELAARS.map((s) => {
            const aan = (keuze?.afwerking[s.sleutel] ?? 0) > 0;
            return (
              <button
                key={s.sleutel}
                className="schakelaar"
                role="switch"
                aria-checked={aan}
                onClick={() => zetAfwerking(s.sleutel, aan ? 0 : 1)}
              >
                <span>{s.label}</span>
                <span className="wip" />
              </button>
            );
          })}
        </div>

        <div className="afsluiter">
          <span className="kleine-noot">
            Eén kleurtabel per look: de voorvertoning hierboven en de export gebruiken precies
            dezelfde.
          </span>
          <button className="knop-groot vol" onClick={() => void verder()} disabled={keuze === null}>
            Verder: exporteren →
          </button>
        </div>
      </aside>
    </div>
  );
}
