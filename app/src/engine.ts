// De enige weg van de interface naar de engine. Elke methode uit
// engine/cve/rpc.py is hier één aanroep; nergens anders invoke().
import { invoke } from "@tauri-apps/api/core";
import type { KaderPunt } from "./speler/uniforms";

export type Check = { naam: string; ok: boolean; detail: string; vereist: boolean };
export type Doctor = { ok: boolean; fouten: number; checks: Check[] };
export type Hallo = { engine: string; versie: string; protocol: number; methodes: string[] };
/** `projecten.naar_dict()` — de staat van één project. */
export type Project = {
  naam: string;
  aantal_clips: number;
  totaal_duur: number;
  heeft_muziek: boolean;
  muziek: string | null;
  is_ingelezen: boolean;
  is_geanalyseerd: boolean;
  heeft_montage: boolean;
  renders: string[];
  gewijzigd: string | null;
  bezig: string | null;
  stap: string | null;
  klaar: boolean;
};

/** Wat het systeem-bestandsvenster mag kiezen — spiegelt media.VIDEO_EXTENSIES. */
export const VIDEO_EXTENSIES = ["mp4", "mov", "m4v", "mkv", "avi", "mts", "webm"];
/** Idem voor muziek — spiegelt media.AUDIO_EXTENSIES. */
export const AUDIO_EXTENSIES = ["mp3", "wav", "m4a", "aac", "flac", "ogg"];

export type Clip = {
  naam: string;              // bestandsnaam — hiermee gaat clip.zet
  id: string | null;         // C01… zodra de ingest gedraaid heeft
  bron: string;              // absoluut pad naar het bronbestand
  duur: number;
  breedte: number;
  hoogte: number;
  fps: number;
  score: number | null;      // beste segmentscore, pas na de analyse
  aan: boolean;
  thumbnail: string | null;  // absoluut pad naar een JPG van ~320 px breed
};

/** Eén soort beelden uit styles/ — bepaalt wat een goed shot is. Wordt
 *  herkend uit het materiaal; zie `stijlkeuze.py`. */
export type Stijl = { naam: string; titel: string; omschrijving: string };
/** Eén montagestijl uit styles/montage/ — bepaalt het snijritme. Veertien
 *  stuks, van Velocity (energie 5) tot Ambient (energie 1). PLAN-v2.md §4.1. */
export type Montagestijl = {
  id: string;
  titel: string;
  energie: number;         // 1..5, de balkjes op de kaart
  omschrijving: string;
  snijritme: string;       // "elke tel", "per maat", "per 4 maten", …
  tellen: number;          // gemiddelde shotlengte in tellen
};
/** Eén titelstijl uit styles/titels/titels.json. Twintig stuks, PLAN-v2.md §4.2.
 *  `voorbeeld` is een absoluut pad naar een PNG van 320×180 met alfa: een echt
 *  frame uit dezelfde compositie die ook rendert, halverwege de animatie. Hij
 *  is `null` zolang dat beeld nog niet gemaakt is — `titelVoorbeelden()` maakt
 *  de ontbrekende. */
export type Titelstijl = {
  id: string;
  naam: string;
  animatie: string;
  voorbeeld: string | null;
};
/** Alleen de vormen die de renderer echt kan — 4:5 zit er bewust niet bij. */
export type Vorm = { naam: "16:9" | "9:16" | "1:1"; breedte: number; hoogte: number };
export type Stijlen = {
  stijlen: Stijl[];
  montagestijlen: Montagestijl[];
  /** Welke energieniveaus onder welk filter vallen: alles/snel/gemiddeld/rustig. */
  banden: Record<string, [number, number]>;
  titelstijlen: Titelstijl[];
  titel_gekozen: string;      // wat er in edl.json staat, of de eerste
  vormen: Vorm[];
  herkend: string | null;     // wat stijlkeuze.py bij dit materiaal vindt
  montage_herkend: string | null;  // de montagestijl die daar standaard bij hoort
  zekerheid?: number;         // 0..1, hoe duidelijk die keuze wint
  uitleg?: string;            // één zin voor de gebruiker
  gemeten?: Record<string, number>;
};

export type Muziek = { bestand: string; bpm: number | null; duur: number | null };

/** Eén genre uit `muziekgen.GENRES`, met het tempo dat er standaard bij hoort. */
export type MuziekGenre = { naam: string; bpm: number };
/** Eén gegenereerde track, zoals de `.json` naast het bestand hem bewaart.
 *  `bpm` is wat aan het model gevraagd is — dat is betrouwbaarder dan
 *  `bpm_gemeten` bij zachte muziek (vendor/ace-step/VERSLAG.md §3). */
export type MuziekVariant = {
  variant: string;            // "A" | "B" | "C"
  pad: string;                // absoluut pad naar de wav
  bestand: string;
  genre: string;
  stemming: string | null;
  zang: boolean;
  bpm: number;
  bpm_gemeten: number | null;
  /** Hoe ver `bpm_gemeten` van `bpm` af ligt, met halve en dubbele tel
   *  meegerekend. `null` = niet te meten (zachte, beatloze muziek). */
  bpm_afwijking?: number | null;
  duur: number;               // ná het wegknippen van de stille staart
  gevraagde_duur: number;
  seed: number;
  prompt: string;
  model: string;
  licentie: string;
  gemaakt: string;
  maten: number;
  stilte_weg: number;         // hoeveel seconden stilte eraf gingen
  fade: number;
};
export type MuziekStatus = {
  aanwezig: boolean;
  pad: string | null;
  bytes: number;
  model: string;
  licentie: string;
  genres: MuziekGenre[];
  uitleg: string;
  varianten?: MuziekVariant[];  // alleen met `project` erbij
  bezig?: boolean;
  /** Loopt er nu een installatie van het model? Machinebreed, niet per project. */
  installeren_bezig?: boolean;
};
export type MuziekOpdracht = {
  genre: string;
  stemming?: string;
  /** Leeg laten: de engine kiest een tempo bij de stijl en het genre. */
  bpm?: number;
  duur?: number;
  zang?: boolean;
  varianten?: number;
  stijl?: string;
};

/** Eén van de drie onderdelen die de titels in de **export** tekenen.
 *  De live speler doet het zelf in WebGPU; de export laat een headless browser
 *  de compositie renderen, en daar zijn node, HyperFrames en die browser voor
 *  nodig. Zie `engine/cve/onderdelen.py`. */
export type Onderdeel = {
  naam: "node" | "hyperframes" | "chrome";
  titel: string;              // in gewone woorden, voor het paneel
  aanwezig: boolean;
  pad: string | null;
  versie: string;
};
export type OnderdelenStatus = {
  alles_klaar: boolean;
  /** Leeg zodra de export titels kan tekenen. */
  ontbreekt: Onderdeel["naam"][];
  onderdelen: Onderdeel[];
  bezig: boolean;
  bytes: number;
  nodig_bytes: number;
  uitleg: string;
};

/** Afwerking zoals `edl.Afwerking` hem kent: alles 0..1, 0 is uit.
 *  De schuiven in het ontwerp staan op 0..100 — dat rekent `Look.tsx` om. */
export type Afwerking = {
  korrel: number;
  halation: number;
  gloed: number;
  vignet: number;
  lichtlek: number;
  breedbeeld: number;
  filmtrilling: number;
  kleurrand: number;
};
/** Eén look uit looks/looks.json, met de afwerking die erbij hoort. */
export type LookInfo = { id: string; naam: string; sfeer: string; afwerking: Partial<Afwerking> };
export type LookKeuze = { id: string; sterkte: number; afwerking: Afwerking };
export type Looks = { looks: LookInfo[]; sferen: string[]; gekozen: LookKeuze };

/** Eén shot op de tijdlijn, uit `bijwerken.montage()`. Tijden in seconden;
 *  `tel` is de index in `Montagestand.tellen` en `tellen` hoeveel tellen het
 *  shot beslaat. `start`, `duur` en `frames` komen uit de muziek en zijn niet
 *  door de gebruiker te wijzigen. */
export type Shot = {
  id: string;
  nr: number;
  clip: string;                 // clip-id (C01…)
  bestand: string;              // bestandsnaam — hiermee gaat clip.voorkeur
  start: number;
  duur: number;
  frames: number;
  tel: number | null;
  tel_afwijking: number | null; // hoeveel het shot naast de tel ligt
  tellen: number;
  bron_in: number;              // seconden in de bronclip
  bron_duur: number;            // = duur × snelheid
  snelheid: number;
  /** De speed-ramp als (uitvoerduur, snelheid)-stukken, dezelfde lijst waar de
   *  renderer mee rekent (`edl.VideoBlok.snelheid_stukken`). Eén stuk bij
   *  constante snelheid, 24 bij een ramp. */
  snelheid_stukken: [number, number][];
  overgang: string;
  /** Hoe lang de overgang duurt. 0 = snede. De speler houdt zo lang twee
   *  beelden naast elkaar; zonder duur is elke overgang een snede. */
  overgang_duur: number;
  zoom: string;
  zoom_kracht: number;
  bevriezen: number;
  vulmodus: string;             // vul | pas | wazig
  /** Herkaderen: waar het venster in de bron valt bij vulmodus `vul`. Leeg of
   *  afwezig is het midden. `{x, y}` is een vast punt, `{punten}` keyframes —
   *  zie `edl.VideoBlok.kader` en `engine/cve/kader.py`. */
  kader?: KaderPunt;
  /** Op welke as er ruimte is om te herkaderen: "x" bij een liggende clip in
   *  een staand canvas, "y" andersom, `null` als het beeld toch al past. De
   *  engine rekent dit uit, zodat de interface de verhoudingen niet hoeft te
   *  kennen. */
  kader_as: "x" | "y" | null;
  proxy: string | null;         // absoluut pad; de speler decodeert dit bestand
  reden: string;
  vast: boolean;
  score: number | null;
  signalen: Record<string, number>;
  moet: boolean;
  nooit: boolean;
  thumbnail: string | null;
};
/** Wat de inspecteur van een clip nodig heeft: filmstrip en scorelijn. */
export type ShotClip = {
  id: string;
  bestand: string;
  duur: number;
  proxy: string | null;
  strip: string | null;         // één JPG met `strip_frames` beeldjes naast elkaar
  strip_frames: number;
  score: { t: number; waarde: number }[];
};
export type Montagestand = {
  project: string;
  stijl: string;
  vorm: string;
  fps: number;
  duur: number;
  bpm: number | null;
  /** `pad` is absoluut: de speler laadt het bestand zelf, want de muziek is
   *  daar de meesterklok en het beeld volgt. */
  muziek: { bestand: string | null; bron_start: number; pad: string | null };
  look: { id: string; sterkte: number };
  afwerking: Afwerking;
  effectseed: number;
  tellen: number[];             // tel-raster in tijdlijntijd
  maten: { tel: number; t: number; nummer: number }[];
  golfvorm: number[];           // ~400 waarden 0..1
  shots: Shot[];
  titels: { id: string; soort: string; start: number; duur: number; tekst: string }[];
  clips: Record<string, ShotClip>;
  voorkeuren: { moet: string[]; nooit: string[] };
};

/** Eén mechanische controle op de render (review.py). */
export type ReviewRegel = { naam: string; ok: boolean; ernst: string; tekst: string };
export type Video = {
  project: string;
  video: string;              // absoluut pad
  naam: string;
  duur: number;
  wanneer: string;            // ISO, UTC
  bytes: number;
  review: ReviewRegel[] | null;
};

/** Ongevraagde berichten van de engine, via listen("engine-gebeurtenis"). */
export type Voortgang = {
  werk: "verwerk" | "maakvideo" | "muziekgen" | "muziekinstall" | "titelvoorbeelden" | "onderdelen";
  /** Leeg bij titelvoorbeelden, muziekinstall en onderdelen: die zijn
   *  machinebreed, niet per project. */
  project: string;
  stap: string;               // "inlezen" | "analyseren" | een fase uit voortgang.py
  gedaan: number;
  totaal: number;
  tekst: string;
  percentage?: number;        // alleen bij maakvideo
  resterend?: number | null;  // geschatte seconden, alleen bij maakvideo
};
export type Montage = {
  werk: "maakvideo";
  project: string;
  video: string;              // absoluut pad naar de mp4
  duur: number;
  geslaagd: boolean;
  review: ReviewRegel[];
  uitleg: string;             // wat de regisseur deed, in gewone taal
  /** Wat de render onderweg niet kon doen zonder te stoppen — titels die niet
   *  getekend konden worden, bijvoorbeeld. Exporteren toont deze regels; ze
   *  mogen nooit alleen in een logbestand staan. */
  waarschuwingen: string[];
};
export type EngineGebeurtenis =
  | { gebeurtenis: "voortgang"; data: Voortgang }
  | { gebeurtenis: "klaar"; data: { werk: "verwerk"; project: string; status: Project } }
  | { gebeurtenis: "klaar"; data: { werk: "muziek"; project: string; muziek: Muziek } }
  | { gebeurtenis: "klaar"; data: { werk: "muziekgen"; project: string; varianten: MuziekVariant[] } }
  | { gebeurtenis: "klaar"; data: { werk: "muziekinstall"; project: string; pad: string; bytes: number; al_aanwezig: boolean } }
  | { gebeurtenis: "klaar"; data: Montage }
  | { gebeurtenis: "klaar"; data: { werk: "titelvoorbeelden"; project: string; titelstijlen: Titelstijl[] } }
  | { gebeurtenis: "klaar"; data: { werk: "onderdelen"; project: string; al_aanwezig: boolean; ontbreekt: string[]; onderdelen: Onderdeel[] } }
  | { gebeurtenis: "fout"; data: { werk?: string; project: string; fout: string; soort: string } };

export const GEBEURTENIS = "engine-gebeurtenis";
export const PROTOCOL = 1;

export function engine<T>(methode: string, params: Record<string, unknown> = {}): Promise<T> {
  return invoke<T>("engine", { methode, params });
}

export const hallo = () => engine<Hallo>("hallo");
export const doctor = () => engine<Doctor>("doctor");
export const projecten = () => engine<Project[]>("projecten");

export const projectMaak = (naam: string) => engine<Project>("project.maak", { naam });
export const projectVoegToe = (project: string, paden: string[]) =>
  engine<{ bestanden: { naam: string; soort?: string; fout?: string }[]; status: Project }>(
    "project.voegtoe", { project, paden });
/** Antwoordt meteen; de voortgang komt als gebeurtenis. */
export const projectVerwerk = (project: string, stijl?: string) =>
  engine<{ gestart: boolean; bezig?: string }>("project.verwerk", { project, stijl });
export const projectClips = (project: string) => engine<Clip[]>("project.clips", { project });
export const clipZet = (project: string, clip: string, aan: boolean) =>
  engine<{ clip: string; aan: boolean; uit: string[] }>("clip.zet", { project, clip, aan });

/** Zet een audiobestand als muziek van het project.
 *  `gestart: true` betekent dat de meting nog loopt; BPM en duur komen dan
 *  als `klaar`-gebeurtenis met `werk: "muziek"`. */
export const projectMuziek = (project: string, pad: string) =>
  engine<Muziek & { gestart: boolean }>("project.muziek", { project, pad });
/** Dezelfde methode zonder pad: alleen lezen wat er nu ligt, of null. */
export const projectMuziekStand = (project: string) =>
  engine<Muziek | null>("project.muziek", { project });
/** Staat het muziekmodel er, en wat is er voor dit project al gegenereerd? */
export const muziekStatus = (project?: string) =>
  engine<MuziekStatus>("muziek.status", { project });
/** Antwoordt meteen; voortgang en de varianten komen als gebeurtenis
 *  (`werk: "muziekgen"`). `bezig: true` = er loopt er al een voor dit project. */
export const muziekGenereer = (project: string, opdracht: MuziekOpdracht) =>
  engine<{ gestart: boolean; bezig: boolean }>("muziek.genereer", { project, ...opdracht });
/** Haal het muziekmodel op (ongeveer 11 GB). Antwoordt meteen; de voortgang
 *  komt als gebeurtenis (`werk: "muziekinstall"`). `gestart: false` = er loopt
 *  er al een. */
export const muziekInstalleer = () => engine<{ gestart: boolean }>("muziek.installeer", {});
/** Breek de installatie af. Wat er al staat blijft staan en is te hervatten. */
export const muziekInstalleerStop = () =>
  engine<{ gestopt: boolean }>("muziek.installeer_stop", {});

/** Staan node, HyperFrames en de browser klaar om titels te tekenen in de
 *  export? Gevraagd bij het opstarten; ontbreekt er iets en is er internet,
 *  dan haalt `useOnderdelen` het op de achtergrond op. */
export const onderdelenStatus = () => engine<OnderdelenStatus>("onderdelen.status", {});
/** Haal op wat er mist (ongeveer 400 MB). Antwoordt meteen; de voortgang komt
 *  als gebeurtenis (`werk: "onderdelen"`). `gestart: false` = er loopt er al een. */
export const onderdelenInstalleer = () =>
  engine<{ gestart: boolean }>("onderdelen.installeer", {});
/** Breek het klaarzetten af. Wat er staat blijft staan en is te hervatten. */
export const onderdelenInstalleerStop = () =>
  engine<{ gestopt: boolean }>("onderdelen.installeer_stop", {});
/** Een gegenereerde variant als projectmuziek zetten. Zelfde route als
 *  `projectMuziek`, dus ook hier komt de BPM-meting als gebeurtenis terug. */
export const muziekKies = (project: string, pad: string) =>
  engine<Muziek & { gestart: boolean }>("muziek.kies", { project, pad });

export const projectStijlen = (project: string) =>
  engine<Stijlen>("project.stijlen", { project });
/** Maak de ontbrekende voorbeeldbeelden van de titelstijlen. Antwoordt meteen
 *  met wat er al is; de rest komt als gebeurtenis (`werk: "titelvoorbeelden"`).
 *  Bij een lege cache is dit een browserrender per stijl. */
export const titelVoorbeelden = (project: string) =>
  engine<{ gestart: boolean; bezig: boolean; titelstijlen: Titelstijl[] }>(
    "titel.voorbeelden", { project });
/** Regie, render en nakijken. Antwoordt meteen; de rest komt als gebeurtenis. */
export const projectMaakVideo = (
  project: string,
  stijl: string,
  montage: string,
  titel: string,
  vorm: Vorm["naam"],
  duur: number | null,
  kwaliteit: "preview" | "eind" = "preview",
  /** Laat weg: dan beslist de engine. Die regisseert alleen opnieuw als er
   *  sinds de montage een andere stijl, vorm of lengte gekozen is — zo kan de
   *  interface het bijgewerkte werk uit stap 4 niet per ongeluk weggooien.
   *  `false` = nooit opnieuw regisseren, wat de knop in stap 4 doet. */
  regie?: boolean,
) => engine<{ gestart: boolean }>("project.maakvideo", {
  project, stijl, montage, titel, vorm, duur, kwaliteit,
  ...(regie === undefined ? {} : { regie }),
});

/** Loopt er ergens een render, analyse of muziekgeneratie? Gevraagd vóór het
 *  installeren van een update: die sluit op Windows de app meteen af. */
export const engineBezig = () =>
  engine<{ bezig: boolean; werk: { project: string; tekst: string }[] }>("bezig", {});
/** De catalogus van 24 looks (plus "origineel") en wat dit project gekozen heeft. */
export const projectLooks = (project: string) => engine<Looks>("project.looks", { project });
export const projectLookZet = (project: string, k: LookKeuze) =>
  engine<LookKeuze>("project.look.zet", { project, ...k });
/** Eén frame door dezelfde keten als de render (compositor), als PNG op schijf.
 *  `breedte: 0` laat hem op canvasformaat staan. */
export const projectLookVoorbeeld = (
  project: string,
  k: LookKeuze,
  breedte: number,
  clip?: string,
) => engine<{ pad: string; uit_cache: boolean; clip: string }>(
  "project.look.voorbeeld", { project, ...k, breedte, clip });

/** Eén overlay zoals de speler hem zelf kan tekenen. `variabelen` is
 *  letterlijk wat de renderer als `--variables` aan HyperFrames geeft. */
export type Titelweb = {
  breedte: number;
  hoogte: number;
  titels: { id: string; soort: string; start: number; duur: number; variabelen: Record<string, unknown> }[];
  /** Overlays waarvan het sjabloon niet in de app zit; die zie je pas in de
   *  render. Liever gemeld dan stil weggelaten. */
  overgeslagen: { id: string; soort: string }[];
};
export const projectTitels = (project: string) =>
  engine<Titelweb>("project.titels", { project });

/** De kleurtabel van een look als `.cube`-tekst; `null` bij "geen".
 *  De speler leest `looks/` niet zelf: het asset-protocol mag alleen bij de
 *  projectmap. Zie `engine/cve/rpc.py` → `look.lut`. */
export const lookLut = (id: string) =>
  engine<{ id: string; cube: string | null }>("look.lut", { id });

/** De montage zoals hij in edl.json staat. `null` = nog geen montage. */
export const projectMontage = (project: string) =>
  engine<Montagestand | null>("project.montage", { project });
/** "moet" | "nooit" | null (voorkeur weghalen), op bestandsnaam. */
export const projectClipVoorkeur = (
  project: string,
  clip: string,
  soort: "moet" | "nooit" | null,
) => engine<{ clip: string; soort: string | null; moet: string[]; nooit: string[] }>(
  "project.clip.voorkeur", { project, clip, soort });
/** Eén shot bijwerken. De tijdlijn verschuift niet — alleen wat erin te zien is. */
export const projectShotZet = (
  project: string,
  shot: string,
  /** `kader: {}` betekent "automatisch": de engine rekent het opnieuw uit de
   *  aandachtspunten. Een gevuld object is een eigen keuze. Laat het weg om
   *  het kader te laten staan zoals het is. */
  wijziging: { snelheid?: number; bron_in?: number; kader?: KaderPunt },
) => engine<Montagestand>("project.shot.zet", { project, shot, ...wijziging });
/** Alleen de regie opnieuw: geen render, geen ffmpeg behalve de beeldjes. */
export const projectRegisseer = (
  project: string,
  stijl?: string,
  montage?: string,
  vorm?: Vorm["naam"],
  duur?: number | null,
) => engine<{ montage: Montagestand; uitleg: string; waarschuwingen: string[] }>(
  "project.regisseer", { project, stijl, montage, vorm, duur });

/** De laatste render van dit project, of null als er nog niets gerenderd is. */
export const projectVideo = (project: string) =>
  engine<Video | null>("project.video", { project });

// De startcontrole op WebGPU. Eén keer bij het opstarten, want een adapter
// opvragen kost tijd en het antwoord verandert niet tijdens een sessie.
// Zonder WebGPU rendert de native compositor (wgpu in Rust) de voorvertoning
// als beeldstroom op lage resolutie — dezelfde shaders, alleen trager.
// Zie PLAN-v2.md §4.4.
export async function webgpuCheck(): Promise<Check> {
  const gpu = (navigator as unknown as { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  if (!gpu) {
    return {
      naam: "WebGPU",
      ok: false,
      vereist: false,
      detail: "niet beschikbaar in deze webview — voorvertoning loopt via de engine, trager",
    };
  }
  try {
    const adapter = await gpu.requestAdapter();
    return adapter
      ? { naam: "WebGPU", ok: true, vereist: false, detail: "adapter gevonden, voorvertoning op de GPU" }
      : { naam: "WebGPU", ok: false, vereist: false, detail: "geen adapter — voorvertoning loopt via de engine, trager" };
  } catch (e) {
    return { naam: "WebGPU", ok: false, vereist: false, detail: `adapter weigerde: ${String(e)}` };
  }
}
