// Proxy's uitpakken en decoderen: mp4box.js voor de demux, WebCodecs voor de
// decode. Eén `Proxy` per proxybestand, één `Blokdecoder` per shot.
//
// Waarom niet gewoon een <video>-element: een `<video>` levert geen frame op
// een gevraagd moment, hij speelt in zijn eigen tempo en met zijn eigen
// buffering. Voor een montage die op de tel moet liggen is dat te los — en bij
// een snede naar een andere clip zou je op een nieuw element moeten wachten.
// Met WebCodecs houden we de frames zelf vast en kunnen we vooruit bufferen.
//
// Let op: elke `VideoFrame` die je niet sluit houdt GPU-geheugen vast. Alles
// wat hier een frame uitdeelt, deelt ook de plicht uit het te sluiten; zie
// `Blokdecoder.pak()`.
import { createFile, DataStream, Endianness, MP4BoxBuffer, type ISOFile, type Sample } from "mp4box";
import { convertFileSrc } from "@tauri-apps/api/core";

/** Hoeveel gedecodeerde frames we per blok vooruit vasthouden. Hoger is
 *  vloeiender en kost geheugen; op 540p is een frame ~1,5 MB op de GPU. */
const BUFFER = 12;

export type ProxyInfo = { breedte: number; hoogte: number; fps: number; duur: number };

/** Hoeveel `VideoFrame`s er op dit moment openstaan, en hoeveel er in totaal
 *  langs zijn geweest. Alleen voor de QA-brug: een frame dat niet gesloten
 *  wordt houdt GPU-geheugen vast, en dat is van buiten niet te zien. Elk
 *  frame gaat via `open()`/`dicht()` hieronder, dus de teller kan niet
 *  achterlopen op de werkelijkheid. */
export const frames = { open: 0, totaal: 0 };

/** De `avcC`/`hvcC`-doos die de decoder nodig heeft om te starten. */
function beschrijving(bestand: ISOFile, trackId: number): Uint8Array | undefined {
  const stsd = bestand.getTrackById(trackId).mdia?.minf?.stbl?.stsd;
  for (const entry of (stsd?.entries ?? []) as unknown as Record<string, unknown>[]) {
    const doos = (entry.avcC ?? entry.hvcC ?? entry.vpcC ?? entry.av1C) as
      | { write(s: DataStream): void }
      | undefined;
    if (!doos) continue;
    const stroom = new DataStream(undefined, 0, Endianness.BIG_ENDIAN);
    doos.write(stroom);
    // De eerste 8 bytes zijn de doos-kop (lengte + type); die hoeven niet mee.
    return new Uint8Array((stroom.buffer as ArrayBuffer).slice(8));
  }
  return undefined;
}

/** Eén proxybestand, gedemuxt en met een sample-index in het geheugen.
 *
 *  De samples van een 540p-proxy van een halve minuut zijn samen een paar MB;
 *  die houden we vast zodat elk shot uit dezelfde clip meteen kan starten.
 */
export class Proxy {
  readonly info: ProxyInfo;
  private constructor(
    readonly samples: Sample[],
    readonly config: VideoDecoderConfig,
    info: ProxyInfo,
  ) {
    this.info = info;
  }

  /** Lees een proxy in. `pad` is een absoluut pad op schijf. */
  static async lees(pad: string): Promise<Proxy> {
    const antwoord = await fetch(convertFileSrc(pad));
    if (!antwoord.ok) throw new Error(`proxy niet te lezen: ${pad} (${antwoord.status})`);
    const ruw = await antwoord.arrayBuffer();

    // `true`: de mdat-inhoud bewaren. Zonder dat komen de samples zonder
    // data terug en heeft de decoder niets te decoderen.
    const bestand = createFile(true);
    type Spoor = { id: number; breedte: number; hoogte: number; fps: number; duur: number };
    let track: Spoor | null = null;
    const samples: Sample[] = [];
    let fout: string | null = null;
    bestand.onError = (module, bericht) => {
      fout = `mp4box ${module}: ${bericht}`;
    };
    bestand.onReady = (info) => {
      const v = info.videoTracks[0];
      if (!v) {
        fout = `geen videospoor in ${pad}`;
        return;
      }
      track = {
        id: v.id,
        breedte: v.video?.width ?? v.track_width,
        hoogte: v.video?.height ?? v.track_height,
        fps: v.samples_duration > 0 ? (v.nb_samples * v.timescale) / v.samples_duration : 30,
        duur: v.duration / (v.timescale || 1),
      };
      bestand.setExtractionOptions(v.id, null, { nbSamples: v.nb_samples });
      bestand.start();
    };
    bestand.onSamples = (_id, _user, nieuwe) => void samples.push(...nieuwe);
    // Alles in één keer: het bestand staat op schijf, er is niets te streamen.
    // `appendBuffer` roept onReady aan, onReady roept start(), start() levert
    // de samples via onSamples — allemaal synchroon, dus hierna is het klaar.
    bestand.appendBuffer(MP4BoxBuffer.fromArrayBuffer(ruw, 0), true);
    bestand.flush();
    if (fout) throw new Error(fout);
    if (!track) throw new Error(`geen moov-doos in ${pad}`);
    if (samples.length === 0) throw new Error(`geen samples in ${pad}`);

    const t: Spoor = track;
    const beschr = beschrijving(bestand, t.id);
    const codec = bestand.getTrackById(t.id).mdia.minf.stbl.stsd.entries[0];
    const config: VideoDecoderConfig = {
      codec: (codec as unknown as { getCodec(): string }).getCodec(),
      codedWidth: t.breedte,
      codedHeight: t.hoogte,
      description: beschr,
      optimizeForLatency: true,
    };
    // Kan deze webview dit codec? Een proxy die met mpeg4 gemaakt is (de
    // terugval op een pc zonder H.264-encoder) komt hier niet door, en dan is
    // een nette melding beter dan een decoder die halverwege omvalt.
    const steun = await VideoDecoder.isConfigSupported(config).catch(() => null);
    if (!steun?.supported) {
      throw new Error(`voorvertoning niet mogelijk voor deze proxy (${config.codec})`);
    }
    // NIET sorteren op `cts`: de samples komen van mp4box in decodeervolgorde
    // (stsc/stts, dus DTS) en zo horen ze de decoder in te gaan. `cts` zegt
    // alleen wanneer een frame in beeld komt; bij B-frames wijkt dat af, en
    // sorteren zet een frame dan vóór het referentieframe dat het nodig heeft.
    return new Proxy(samples, config, {
      breedte: t.breedte,
      hoogte: t.hoogte,
      fps: t.fps,
      duur: t.duur,
    });
  }

  /** De index van de keyframe die op of vóór `t` (seconden) in beeld komt.
   *
   *  Geen `break` bij de eerste sample voorbij `t`: in decodeervolgorde loopt
   *  `cts` niet op. De hele lijst doorlopen kost op een proxy van een halve
   *  minuut ~900 vergelijkingen — dat is niets, en het is wél correct. */
  keyframeVoor(t: number): number {
    let gevonden = 0;
    let beste = -Infinity;
    for (let i = 0; i < this.samples.length; i++) {
      const s = this.samples[i];
      if (!s.is_sync) continue;
      const cts = s.cts / s.timescale;
      if (cts <= t && cts > beste) {
        beste = cts;
        gevonden = i;
      }
    }
    return gevonden;
  }

  /** De hoogste decodeer-index waarvan het frame op of vóór `t` in beeld komt.
   *
   *  Dit is de grens tot waar `Blokdecoder.vul()` mag voeren. Alles tot die
   *  index is of zelf nodig, of het referentieframe van iets dat nodig is. */
  laatsteVoor(t: number): number {
    let gevonden = 0;
    for (let i = 0; i < this.samples.length; i++) {
      const s = this.samples[i];
      if (s.cts / s.timescale <= t) gevonden = i;
    }
    return gevonden;
  }
}

/** Brontijd (seconden in de proxy) voor een moment binnen een blok.
 *
 *  De integraal van de snelheid over de stukken: hetzelfde sommetje als
 *  `edl.VideoBlok.bron_lengte`, maar tot `inBlok` in plaats van tot het eind.
 *  Voorbij het blok loopt hij door met de laatste snelheid — tijdens een
 *  overgang hoort het uitgaande blok bewegend beeld te houden.
 *
 *  Staat hier los van `Blokdecoder` zodat de QA-brug hem naast de engine kan
 *  leggen zonder een decoder te hoeven maken.
 */
export function brontijdVan(
  stukken: readonly (readonly [number, number])[],
  bronStart: number,
  bevriezen: number,
  inBlok: number,
): number {
  const duur = stukken.reduce((s, [d]) => s + d, 0);
  const grens = duur - bevriezen;
  let over = Math.max(0, bevriezen > 0 ? Math.min(inBlok, grens) : inBlok);
  let bron = 0;
  for (const [d, v] of stukken) {
    if (over <= d) return bronStart + bron + over * v;
    bron += d * v;
    over -= d;
  }
  const laatsteV = stukken[stukken.length - 1]?.[1] ?? 1;
  return bronStart + bron + over * laatsteV;
}

/** Eén shot: decodeert de bronframes van dat blok, op aanvraag per moment.
 *
 *  `tijd()` is tijdlijntijd binnen het blok (0 = begin van het blok); de
 *  omrekening naar brontijd (snelheid, bevriezen) zit hier, niet in de speler.
 */
export class Blokdecoder {
  private decoder: VideoDecoder;
  private wachtrij: VideoFrame[] = [];
  private volgende: number;
  /** Tot en met deze decodeer-index mag `vul()` voeren. */
  private grensIndex: number;
  private laatste: VideoFrame | null = null;
  private kapot: string | null = null;
  /** Bronmateriaal dat het blok opmaakt: `sum(duur × snelheid)`. */
  private readonly bronDuur: number;

  /** `stukken` is dezelfde lijst (uitvoerduur, snelheid) als
   *  `edl.VideoBlok.snelheid_stukken()`: één stuk bij constante snelheid, 24
   *  stukken bij een speed-ramp. Daarmee eet de voorvertoning precies zoveel
   *  bron als de renderer, en liggen de beelden midden in het shot op dezelfde
   *  tel. */
  constructor(
    private proxy: Proxy,
    private bronStart: number,
    private stukken: readonly (readonly [number, number])[],
    private bevriezen: number,
  ) {
    this.bronDuur = stukken.reduce((s, [d, v]) => s + d * v, 0);
    this.volgende = proxy.keyframeVoor(bronStart);
    // Een halve seconde marge: de laatste frames van een blok mogen niet
    // ontbreken omdat cts en duur net niet op elkaar vallen, en tijdens een
    // overgang loopt het uitgaande blok nog even door.
    this.grensIndex = proxy.laatsteVoor(bronStart + this.bronDuur + 0.5);
    this.decoder = new VideoDecoder({
      output: (frame) => {
        frames.open++;
        frames.totaal++;
        this.wachtrij.push(frame);
      },
      error: (e) => {
        this.kapot = String(e);
      },
    });
    this.decoder.configure(proxy.config);
    this.vul();
  }

  get fout(): string | null {
    return this.kapot;
  }

  /** Eén frame sluiten en de teller bijwerken. Elk frame dat hier niet langs
   *  komt is een lek dat niemand ziet. */
  private dicht(f: VideoFrame | null): void {
    if (!f) return;
    f.close();
    frames.open--;
  }

  /** Brontijd (seconden in de proxy) voor een moment binnen het blok.
   *
   *  Niet geklemd op de blokduur: tijdens een overgang loopt het uitgaande
   *  blok nog even door, en dan hoort daar bewegend beeld te staan en geen
   *  bevroren laatste frame. `vul()` houdt daar een halve seconde marge voor.
   *  Wél geklemd als het blok een `bevriezen` heeft — dat is een keuze. */
  bronTijd(inBlok: number): number {
    return brontijdVan(this.stukken, this.bronStart, this.bevriezen, inBlok);
  }

  /** Stuur zoveel samples naar de decoder dat de buffer weer vol is.
   *
   *  De grens is een decodeer-index, geen cts-vergelijking: in
   *  decodeervolgorde kan een frame dat laat in beeld komt vóór een frame
   *  staan dat nog nodig is, en een `break` op cts zou dat laatste overslaan. */
  private vul(): void {
    while (
      this.wachtrij.length + this.decoder.decodeQueueSize < BUFFER &&
      this.volgende <= this.grensIndex &&
      this.volgende < this.proxy.samples.length &&
      this.decoder.state === "configured"
    ) {
      const s = this.proxy.samples[this.volgende++];
      this.decoder.decode(
        new EncodedVideoChunk({
          type: s.is_sync ? "key" : "delta",
          timestamp: (s.cts / s.timescale) * 1e6,
          duration: (s.duration / s.timescale) * 1e6,
          data: s.data as Uint8Array<ArrayBuffer>,
        }),
      );
    }
  }

  /** Het frame dat op dit moment in beeld hoort. Niet sluiten: de decoder
   *  houdt hem vast tot er een nieuwer frame nodig is. `null` = nog niets. */
  pak(inBlok: number): VideoFrame | null {
    const doel = this.bronTijd(inBlok) * 1e6;
    // Alles wegwerken wat al voorbij is, op het laatste na — dat blijft staan
    // zodat een haperende decoder geen zwart beeld geeft.
    while (this.wachtrij.length > 0 && this.wachtrij[0].timestamp <= doel) {
      this.dicht(this.laatste);
      this.laatste = this.wachtrij.shift()!;
    }
    if (!this.laatste && this.wachtrij.length > 0) {
      // Vóór het eerste frame: toon dat eerste frame in plaats van zwart.
      this.laatste = this.wachtrij.shift()!;
    }
    this.vul();
    return this.laatste;
  }

  /** Terugspoelen binnen hetzelfde blok (scrubben). */
  herstart(): void {
    for (const f of this.wachtrij) this.dicht(f);
    this.wachtrij = [];
    this.dicht(this.laatste);
    this.laatste = null;
    this.volgende = this.proxy.keyframeVoor(this.bronStart);
    if (this.decoder.state === "configured") this.decoder.reset();
    if (this.decoder.state !== "closed") this.decoder.configure(this.proxy.config);
    this.vul();
  }

  sluit(): void {
    for (const f of this.wachtrij) this.dicht(f);
    this.wachtrij = [];
    this.dicht(this.laatste);
    this.laatste = null;
    if (this.decoder.state !== "closed") this.decoder.close();
  }
}
