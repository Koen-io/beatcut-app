// De keuze in het exportmenu: standaard, bewaren, en heel houden.
//
// Los van `ExportMenu.tsx` omdat dit het deel is dat stil fout kan gaan: een
// bewaarde keuze van gisteren die vandaag niet meer kan (ProRes in MP4 na een
// formaatwissel, H.265 op een computer die het niet kan maken). De engine
// weigert zo'n combinatie met een foutmelding; hier zorgen we dat het menu
// hem nooit aanbiedt.
import type { Exportkeuze, Exportmogelijkheden } from "./engine";

/** Precies wat de render zelf maakt. Wie dit laat staan krijgt de video
 *  zonder extra omzetting — zie `Keuze.is_master()` in engine/cve/export.py. */
export const STANDAARD: Exportkeuze = {
  container: "mp4",
  codec: "h264",
  resolutie: "bron",
  fps: "bron",
  kwaliteit: "standaard",
  bitrate: 12,
  prores: "hq",
  audio: "aac",
  audio_kbps: 192,
  samplerate: 48000,
  map: "",
  naam: "",
};

const SLEUTEL = "beatcut.export";
/** Na afloop de map openen? Apart bewaard: het is geen eigenschap van het bestand. */
const TOON_SLEUTEL = "beatcut.export.toon";

type Opslag = Pick<Storage, "getItem" | "setItem">;

/** De bewaarde keuze, of de standaard. De naam hoort bij één video en wordt
 *  daarom niet bewaard: een tweede project zou anders de naam van het eerste
 *  krijgen. De map wél — wie naar zijn Bureaublad exporteert doet dat steeds. */
export function laad(opslag: Opslag): Exportkeuze {
  try {
    const ruw: unknown = JSON.parse(opslag.getItem(SLEUTEL) ?? "null");
    if (ruw === null || typeof ruw !== "object") return { ...STANDAARD };
    const uit: Record<string, unknown> = { ...STANDAARD };
    for (const [k, v] of Object.entries(STANDAARD)) {
      const w = (ruw as Record<string, unknown>)[k];
      // Alleen overnemen wat van hetzelfde soort is; de rest blijft standaard.
      if (typeof w === typeof v && (typeof w !== "number" || Number.isFinite(w))) uit[k] = w;
    }
    return { ...(uit as Exportkeuze), naam: "" };
  } catch {
    return { ...STANDAARD };
  }
}

export function bewaar(opslag: Opslag, keuze: Exportkeuze): void {
  try {
    opslag.setItem(SLEUTEL, JSON.stringify({ ...keuze, naam: "" }));
  } catch {
    // Volle of geblokkeerde opslag: dan onthoudt hij het niet. Geen reden om
    // de export tegen te houden.
  }
}

export function laadToon(opslag: Opslag): boolean {
  try {
    return opslag.getItem(TOON_SLEUTEL) === "ja";
  } catch {
    return false;
  }
}
export function bewaarToon(opslag: Opslag, aan: boolean): void {
  try {
    opslag.setItem(TOON_SLEUTEL, aan ? "ja" : "nee");
  } catch {
    // zie `bewaar`
  }
}

/**
 * Maak van een keuze er een die op deze computer en in dit formaat kan.
 *
 * Verandert zo min mogelijk: alleen wat niet (meer) past valt terug, en dan op
 * het eerste dat het formaat wél aankan. Zo blijft bij een wissel van MOV naar
 * MP4 je resolutie en je map staan en verandert alleen ProRes in H.264.
 */
export function pasAan(keuze: Exportkeuze, m: Exportmogelijkheden): Exportkeuze {
  const uit = { ...keuze };
  const container = m.containers.find((c) => c.id === uit.container) ?? m.containers[0];
  if (container === undefined) return { ...STANDAARD, map: keuze.map, naam: keuze.naam };
  uit.container = container.id;
  // `container.video` bevat alleen codecs die deze computer kan maken.
  if (!container.video.includes(uit.codec)) uit.codec = container.video[0] ?? "h264";
  if (!container.audio.includes(uit.audio)) uit.audio = container.audio[0] ?? "aac";
  if (!m.resoluties.some((r) => r.id === uit.resolutie)) uit.resolutie = "bron";
  if (uit.fps !== "bron" && !m.fps.includes(Number(uit.fps))) uit.fps = "bron";
  // Dezelfde snelheid als de montage ís "zoals de montage". Zonder dit denkt
  // de engine dat er omgezet moet worden terwijl er niets verandert.
  if (uit.fps !== "bron" && Number(uit.fps) === m.bron.fps) uit.fps = "bron";
  if (!m.kwaliteit.some((q) => q.id === uit.kwaliteit)) uit.kwaliteit = "standaard";
  if (!m.prores.some((p) => p.id === uit.prores)) uit.prores = "hq";
  if (!m.audio_kbps.includes(uit.audio_kbps)) uit.audio_kbps = 192;
  if (!m.samplerates.includes(uit.samplerate)) uit.samplerate = 48000;
  if (!Number.isFinite(uit.bitrate)) uit.bitrate = STANDAARD.bitrate;
  uit.bitrate = Math.min(m.bitrate.max, Math.max(m.bitrate.min, uit.bitrate));
  return uit;
}

/** Een voorinstelling is de standaard met een paar afwijkingen; map en naam
 *  zijn van de gebruiker en blijven staan. */
export function metVoorinstelling(
  keuze: Exportkeuze,
  voor: Partial<Exportkeuze>,
  m: Exportmogelijkheden,
): Exportkeuze {
  return pasAan({ ...STANDAARD, ...voor, map: keuze.map, naam: keuze.naam }, m);
}

/** Welke voorinstelling staat er nu? `null` = iets eigens. */
export function actieveVoorinstelling(keuze: Exportkeuze, m: Exportmogelijkheden): string | null {
  const zelfde = (a: Exportkeuze, b: Exportkeuze) =>
    (Object.keys(STANDAARD) as (keyof Exportkeuze)[])
      // Bitrate en ProRes-profiel tellen alleen als ze iets doen.
      .filter((k) => k !== "map" && k !== "naam")
      .filter((k) => k !== "bitrate" || a.kwaliteit === "eigen")
      .filter((k) => k !== "prores" || a.codec === "prores")
      .every((k) => a[k] === b[k]);
  return m.voorinstellingen.find((v) => zelfde(keuze, metVoorinstelling(keuze, v.keuze, m)))?.id ?? null;
}

/** Is dit precies wat de render al maakt? Dan komt er geen omzetting achteraan. */
export function isStandaard(keuze: Exportkeuze): boolean {
  return (
    keuze.container === "mp4" && keuze.codec === "h264" && keuze.resolutie === "bron" &&
    keuze.fps === "bron" && keuze.kwaliteit === "standaard" && keuze.audio === "aac" &&
    keuze.audio_kbps === 192 && keuze.samplerate === 48000
  );
}

/** Bits per seconde als "9,3 Mbit/s" of "192 kbit/s". */
export function bitrateTekst(bps: number): string {
  if (bps >= 1_000_000) {
    const mbit = bps / 1_000_000;
    return `${mbit >= 100 ? Math.round(mbit) : mbit.toFixed(1).replace(".", ",")} Mbit/s`;
  }
  return `${Math.round(bps / 1000)} kbit/s`;
}

/** Tekens die in een bestandsnaam niet mogen (Windows is hier de strengste). */
export function schoneNaam(naam: string): string {
  return naam.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "");
}
