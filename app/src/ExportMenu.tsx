// Het exportmenu: hoe de video de deur uit gaat.
//
// Opbouw, van boven naar beneden, van "ik wil gewoon een video" naar "ik weet
// precies wat ik wil":
//
//   1. Voorinstellingen — één klik, voor wie het niet uit wil zoeken.
//   2. Wat eruit komt — maat, bitrate, geschatte grootte, waar het komt.
//   3. Beeld, Geluid en Bestand — elk een uitklapbaar blok met alle knoppen.
//
// De standaard is precies wat de render zelf maakt; dan komt er geen
// omzetting achteraan en staat hier dat ook. Wat deze computer niet kan maken
// (H.265 zonder de chip ervoor) staat er niet tussen: de lijsten komen uit
// `export.mogelijkheden`, en de engine is de enige die dat weet.
import { useEffect, useState, type ReactNode } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import {
  exportSchat,
  type Exportkeuze,
  type Exportmogelijkheden,
  type Exportschatting,
} from "./engine";
import {
  actieveVoorinstelling, bitrateTekst, isStandaard, metVoorinstelling, pasAan, schoneNaam,
  STANDAARD,
} from "./exportinstellingen";
import { bytesTekst, getal } from "./format";
import { EDITIE } from "./editie";

/** Wachttijd na de laatste wijziging voor de schatting ververst. */
const RUST_MS = 200;
/** Een pad wordt van rechts afgekapt (`direction: rtl`), zodat je het eind
 *  leest. Zonder dit teken verhuist de eerste "/" dan naar achteren. */
const LRM = "\u200E";

type Props = {
  project: string;
  mogelijkheden: Exportmogelijkheden;
  keuze: Exportkeuze;
  setKeuze: (k: Exportkeuze) => void;
  toonNaAfloop: boolean;
  setToonNaAfloop: (aan: boolean) => void;
  /** Tijdens een render staat alles vast: de keuze is al onderweg. */
  bezig: boolean;
  toonIn: string;
};

export default function ExportMenu({
  project, mogelijkheden: m, keuze, setKeuze, toonNaAfloop, setToonNaAfloop, bezig, toonIn,
}: Props) {
  const [schatting, setSchatting] = useState<Exportschatting | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [open_, setOpen] = useState<"beeld" | "geluid" | "bestand" | null>(null);

  /** Elke wijziging loopt hierlangs, zodat er nooit een combinatie staat die
   *  niet kan. */
  const zet = (deel: Partial<Exportkeuze>) => setKeuze(pasAan({ ...keuze, ...deel }, m));

  // Wat eruit komt rekent de engine uit: die kent het canvas, de duur en de
  // schijf. Debounce, want aan de bitrateschuif draaien geeft tientallen
  // wijzigingen per seconde.
  const sleutel = JSON.stringify(keuze);
  useEffect(() => {
    let geldig = true;
    const t = setTimeout(() => {
      exportSchat(project, keuze)
        .then((s) => {
          if (!geldig) return;
          setSchatting(s);
          setFout(null);
        })
        .catch((e) => {
          if (!geldig) return;
          setSchatting(null);
          setFout(String(e));
        });
    }, RUST_MS);
    return () => {
      geldig = false;
      clearTimeout(t);
    };
    // `keuze` zit in `sleutel`; het object zelf is elke render nieuw.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, sleutel]);

  async function kiesMap() {
    const map = await open({
      title: "Map voor de export kiezen",
      directory: true,
      multiple: false,
      defaultPath: keuze.map || undefined,
    });
    if (typeof map === "string") zet({ map });
  }

  const container = m.containers.find((c) => c.id === keuze.container);
  const codec = m.codecs.find((c) => c.id === keuze.codec);
  const audio = m.audio.find((a) => a.id === keuze.audio);
  const resolutie = m.resoluties.find((r) => r.id === keuze.resolutie);
  const voorinstelling = actieveVoorinstelling(keuze, m);
  const prores = keuze.codec === "prores";
  const fps = keuze.fps === "bron" ? m.bron.fps : Number(keuze.fps);
  const mapTekst = keuze.map || m.standaardmap;

  return (
    <fieldset className="exportmenu" disabled={bezig}>
      <div className="groep">
        <span className="kop-klein">Voorinstelling</span>
        <div className="chip-rij">
          {m.voorinstellingen.map((v) => (
            <button
              key={v.id}
              className="chip-knop"
              aria-pressed={v.id === voorinstelling}
              title={v.uitleg}
              onClick={() => setKeuze(metVoorinstelling(keuze, v.keuze, m))}
            >
              {v.label}
            </button>
          ))}
          {voorinstelling === null && (
            <span className="chip-knop eigen" aria-pressed="true">Eigen instelling</span>
          )}
        </div>
        <span className="kleine-noot">
          {m.voorinstellingen.find((v) => v.id === voorinstelling)?.uitleg ??
            `Je eigen keuze uit de blokken hieronder. ${EDITIE.naam} onthoudt hem voor de volgende keer.`}
        </span>
      </div>

      <div className="export-uitkomst" role="status">
        <div className="export-uitkomst-kop">
          <b>
            {container?.label} · {codec?.label}
            {prores && ` ${m.prores.find((p) => p.id === keuze.prores)?.label ?? ""}`}
          </b>
          <span className="mono">
            {schatting !== null && schatting.duur > 0 ? `± ${bytesTekst(schatting.bytes)}` : "—"}
          </span>
        </div>
        <dl className="export-feiten">
          <dt>Beeld</dt>
          <dd className="mono">
            {schatting !== null ? `${schatting.breedte}×${schatting.hoogte}` : "…"} ·{" "}
            {getal(fps, Number.isInteger(fps) ? 0 : 2)} fps
            {schatting !== null && ` · ${bitrateTekst(schatting.video_bps)}`}
          </dd>
          <dt>Geluid</dt>
          <dd className="mono">
            {keuze.audio === "geen"
              ? "geen"
              : `${audio?.label} · ${
                  keuze.audio === "aac" ? `${keuze.audio_kbps} kbit/s · ` : ""
                }${getal(keuze.samplerate / 1000, 1)} kHz`}
          </dd>
          <dt>Komt in</dt>
          <dd className="mono pad" title={schatting?.pad ?? mapTekst}>
            {LRM}{schatting?.pad ?? mapTekst}
          </dd>
        </dl>
        {fout !== null && <span className="noot-waarschuwing">{fout}</span>}
        {schatting !== null && !schatting.map_bestaat && (
          <span className="noot-waarschuwing">
            Deze map bestaat niet meer. Kies een andere bij Bestand.
          </span>
        )}
        {schatting !== null && !schatting.past && schatting.vrij !== null && (
          <span className="noot-waarschuwing">
            Dit past waarschijnlijk niet: er is nog {bytesTekst(schatting.vrij)} vrij op die schijf.
          </span>
        )}
        <span className="kleine-noot">
          {isStandaard(keuze)
            ? `Dit is de video zoals ${EDITIE.naam} hem rendert — er komt geen extra omzetting aan te pas.`
            : `${EDITIE.naam} rendert eerst op volle kwaliteit en schrijft de video daarna weg in dit formaat.`}
        </span>
      </div>

      <Blok
        titel="Beeld"
        samenvatting={`${resolutie?.id === "bron" ? "Zoals de montage" : resolutie?.label} · ${
          prores ? "ProRes" : m.kwaliteit.find((q) => q.id === keuze.kwaliteit)?.label
        }`}
        open={open_ === "beeld"}
        onWissel={() => setOpen(open_ === "beeld" ? null : "beeld")}
      >
        <Veld label="Bestandsformaat" uitleg={container?.uitleg}>
          <Segment
            naam="Bestandsformaat"
            opties={m.containers.filter((c) => c.video.length > 0)}
            waarde={keuze.container}
            onKies={(container) => zet({ container })}
          />
        </Veld>
        <Veld label="Codec" uitleg={codec?.uitleg}>
          <Segment
            naam="Codec"
            opties={m.codecs.filter((c) => container?.video.includes(c.id))}
            waarde={keuze.codec}
            onKies={(codec) => zet({ codec })}
          />
          {m.codecs.some((c) => !c.beschikbaar) && (
            <span className="kleine-noot">
              Niet op deze computer:{" "}
              {m.codecs.filter((c) => !c.beschikbaar).map((c) => c.label).join(", ")}.
            </span>
          )}
        </Veld>
        <Veld
          label="Resolutie"
          uitleg={
            resolutie?.opgeschaald
              ? "Groter dan de montage: het beeld wordt opgerekt, er komt geen detail bij."
              : undefined
          }
        >
          <select
            className="export-kies"
            aria-label="Resolutie"
            value={keuze.resolutie}
            onChange={(e) => zet({ resolutie: e.target.value })}
          >
            {m.resoluties.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id === "bron"
                  ? r.label
                  : `${r.label} — ${r.breedte}×${r.hoogte}${r.opgeschaald ? " (opgeschaald)" : ""}`}
              </option>
            ))}
          </select>
        </Veld>
        <Veld
          label="Beeldsnelheid"
          uitleg={
            keuze.fps !== "bron" && Number(keuze.fps) > m.bron.fps
              ? "Hoger dan de montage: beelden worden herhaald, het wordt er niet vloeiender van."
              : keuze.fps !== "bron" && Number(keuze.fps) < m.bron.fps
                ? "Lager dan de montage: er vallen beelden weg. De snedes blijven op de tel."
                : undefined
          }
        >
          <select
            className="export-kies"
            aria-label="Beeldsnelheid"
            value={keuze.fps}
            onChange={(e) => zet({ fps: e.target.value })}
          >
            <option value="bron">Zoals de montage ({getal(m.bron.fps, 0)} fps)</option>
            {m.fps.filter((f) => f !== m.bron.fps).map((f) => (
              <option key={f} value={String(f)}>{f} fps</option>
            ))}
          </select>
        </Veld>
        {prores ? (
          <Veld
            label="ProRes-profiel"
            uitleg="ProRes kent geen bitrate maar profielen. HQ is de gangbare keuze voor montage."
          >
            <Segment
              naam="ProRes-profiel"
              opties={m.prores}
              waarde={keuze.prores}
              onKies={(prores) => zet({ prores })}
            />
          </Veld>
        ) : (
          <Veld
            label="Kwaliteit"
            uitleg={
              keuze.kwaliteit === "eigen"
                ? undefined
                : schatting !== null
                  ? `${EDITIE.naam} kiest de bitrate bij deze maat: ${bitrateTekst(schatting.video_bps)}.`
                  : undefined
            }
          >
            <Segment
              naam="Kwaliteit"
              opties={m.kwaliteit}
              waarde={keuze.kwaliteit}
              onKies={(kwaliteit) =>
                zet(
                  kwaliteit === "eigen" && keuze.kwaliteit !== "eigen" && schatting !== null
                    // Begin bij wat er stond, niet bij een willekeurig getal.
                    ? { kwaliteit, bitrate: Math.round(schatting.video_bps / 100_000) / 10 }
                    : { kwaliteit },
                )
              }
            />
            {keuze.kwaliteit === "eigen" && (
              <div className="groep-schuif">
                <div className="schuif-kop">
                  <label htmlFor="export-bitrate">Bitrate</label>
                  <span className="export-getal">
                    <Getalveld
                      label="Bitrate in Mbit/s"
                      min={m.bitrate.min}
                      max={m.bitrate.max}
                      waarde={keuze.bitrate}
                      onKies={(bitrate) => zet({ bitrate })}
                    />
                    <span className="mono">Mbit/s</span>
                  </span>
                </div>
                <input
                  id="export-bitrate"
                  type="range"
                  min={m.bitrate.min}
                  max={80}
                  step={0.5}
                  value={Math.min(80, keuze.bitrate)}
                  onChange={(e) => zet({ bitrate: Number(e.target.value) })}
                />
              </div>
            )}
          </Veld>
        )}
      </Blok>

      <Blok
        titel="Geluid"
        samenvatting={
          keuze.audio === "geen"
            ? "Geen geluid"
            : `${audio?.label}${keuze.audio === "aac" ? ` · ${keuze.audio_kbps} kbit/s` : ""}`
        }
        open={open_ === "geluid"}
        onWissel={() => setOpen(open_ === "geluid" ? null : "geluid")}
      >
        <Veld label="Geluidsformaat" uitleg={audio?.uitleg}>
          <select
            className="export-kies"
            aria-label="Geluidsformaat"
            value={keuze.audio}
            onChange={(e) => zet({ audio: e.target.value })}
          >
            {m.audio.filter((a) => container?.audio.includes(a.id)).map((a) => (
              <option key={a.id} value={a.id}>{a.label}</option>
            ))}
          </select>
        </Veld>
        {keuze.audio === "aac" && (
          <Veld label="Bitrate" uitleg="192 is ruim voor muziek onder video; 320 is het maximum dat zin heeft.">
            <Segment
              naam="Geluidsbitrate"
              opties={m.audio_kbps.map((k) => ({ id: String(k), label: String(k) }))}
              waarde={String(keuze.audio_kbps)}
              onKies={(k) => zet({ audio_kbps: Number(k) })}
            />
          </Veld>
        )}
        {keuze.audio !== "geen" && (
          <Veld label="Samplefrequentie" uitleg="48 kHz is de norm voor video; 44,1 kHz is die van cd's.">
            <Segment
              naam="Samplefrequentie"
              opties={m.samplerates.map((s) => ({
                id: String(s), label: `${getal(s / 1000, 1)} kHz`,
              }))}
              waarde={String(keuze.samplerate)}
              onKies={(s) => zet({ samplerate: Number(s) })}
            />
          </Veld>
        )}
        <span className="kleine-noot">
          Het volume staat altijd op −14 LUFS, de norm van YouTube, Instagram en TikTok.
        </span>
      </Blok>

      <Blok
        titel="Bestand"
        samenvatting={keuze.map ? "Eigen map" : "Bij het project"}
        open={open_ === "bestand"}
        onWissel={() => setOpen(open_ === "bestand" ? null : "bestand")}
      >
        <Veld label="Naam" uitleg="Bestaat de naam al, dan komt er een volgnummer achter. Er wordt nooit iets overschreven.">
          <span className="export-naam">
            <input
              className="export-tekst"
              type="text"
              aria-label="Bestandsnaam"
              placeholder={project}
              maxLength={120}
              value={keuze.naam}
              onChange={(e) => zet({ naam: schoneNaam(e.target.value) })}
            />
            <span className="mono">.{keuze.container}</span>
          </span>
        </Veld>
        <Veld label="Map">
          <span className="export-map mono" title={mapTekst}>{LRM}{mapTekst}</span>
          <div className="knop-rij">
            <button className="knop" onClick={() => void kiesMap()}>Kies map…</button>
            <button className="knop" disabled={keuze.map === ""} onClick={() => zet({ map: "" })}>
              Bij het project
            </button>
          </div>
        </Veld>
        <button
          className="schakelaar"
          role="switch"
          aria-checked={toonNaAfloop}
          onClick={() => setToonNaAfloop(!toonNaAfloop)}
        >
          <span>{toonIn} als het klaar is</span>
          <span className="wip" />
        </button>
      </Blok>

      <button
        className="knop-stil export-terug"
        disabled={voorinstelling === "standaard" && keuze.map === "" && keuze.naam === ""}
        onClick={() => setKeuze(pasAan({ ...STANDAARD }, m))}
      >
        Alles terug naar standaard
      </button>
    </fieldset>
  );
}

/** Een uitklapbaar blok. Dicht toont het in één regel wat er gekozen is, zodat
 *  het menu ook dichtgeklapt alles vertelt. */
function Blok({ titel, samenvatting, open, onWissel, children }: {
  titel: string; samenvatting: string; open: boolean; onWissel: () => void; children: ReactNode;
}) {
  const id = `export-blok-${titel.toLowerCase()}`;
  return (
    <section className={`export-blok${open ? " open" : ""}`}>
      <button className="export-blok-kop" aria-expanded={open} aria-controls={id} onClick={onWissel}>
        <b>{titel}</b>
        <span>{samenvatting}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && <div className="export-blok-inhoud" id={id}>{children}</div>}
    </section>
  );
}

function Veld({ label, uitleg, children }: { label: string; uitleg?: string; children: ReactNode }) {
  return (
    <div className="export-veld">
      <span className="export-label">{label}</span>
      {children}
      {uitleg !== undefined && <span className="kleine-noot">{uitleg}</span>}
    </div>
  );
}

/** Een getal dat je kunt typen. De tekst is van het veld zelf tot je het
 *  verlaat of Enter geeft: wie "0,5" of "12" wil tikken moet onderweg een leeg
 *  veld en een "1" kunnen hebben zonder dat het menu het getal terugzet. */
function Getalveld({ label, min, max, waarde, onKies }: {
  label: string; min: number; max: number; waarde: number; onKies: (v: number) => void;
}) {
  const [tekst, setTekst] = useState(String(waarde).replace(".", ","));
  // Verandert het getal van buiten (de schuif), dan volgt het veld.
  useEffect(() => setTekst(String(waarde).replace(".", ",")), [waarde]);

  function leg_vast() {
    const v = Number(tekst.replace(",", "."));
    if (Number.isFinite(v) && v > 0) {
      const geklemd = Math.min(max, Math.max(min, v));
      onKies(geklemd);
      setTekst(String(geklemd).replace(".", ","));
    } else {
      setTekst(String(waarde).replace(".", ","));
    }
  }

  return (
    <input
      className="export-tekst smal mono"
      type="text"
      inputMode="decimal"
      aria-label={label}
      value={tekst}
      onChange={(e) => setTekst(e.target.value)}
      onBlur={leg_vast}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

function Segment({ naam, opties, waarde, onKies }: {
  naam: string; opties: { id: string; label: string }[]; waarde: string; onKies: (id: string) => void;
}) {
  return (
    <div className="segment" role="group" aria-label={naam}>
      {opties.map((o) => (
        <button key={o.id} aria-pressed={o.id === waarde} onClick={() => onKies(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
