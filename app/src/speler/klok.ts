// De klok van de speler. De muziek is de meester, het beeld volgt.
//
// Waarom zo: BeatCut snijdt op de tel. Loopt het beeld voorop en de muziek
// achter, dan ligt de montage hoorbaar naast de beat — en dat is precies wat
// deze app belooft op te lossen. De `AudioContext` heeft een eigen, stabiele
// tijdbasis; `performance.now()` loopt mee met de tekenlus en verschuift bij
// elke hapering. Dus: is er muziek, dan komt de tijd uit WebAudio.
//
// Zonder muziek valt hij terug op `performance.now()`. Dat is geen compromis:
// zonder audio is er niets om naast te liggen.
import { convertFileSrc } from "@tauri-apps/api/core";

export class Klok {
  private ctx: AudioContext | null = null;
  private buffer: AudioBuffer | null = null;
  private bron: AudioBufferSourceNode | null = null;
  /** Waar de tijdlijn stond toen we begonnen te spelen. */
  private vanaf = 0;
  /** `ctx.currentTime` (of performance.now in seconden) op dat moment. */
  private begin = 0;
  private loopt = false;
  /** Seconden in het muziekbestand die bij tijdlijn 0 horen. */
  private bronStart = 0;
  /** Loopnummer: elke `laad()` onthoudt het nummer dat gold toen hij begon en
   *  laat zijn uitkomst vallen als `sluit()` het inmiddels verhoogd heeft.
   *  Zonder dat maakt een trage fetch na het opruimen alsnog een
   *  `AudioContext` aan, en die blijft dan voorgoed open staan. */
  private ronde = 0;

  get speelt(): boolean {
    return this.loopt;
  }

  get heeftMuziek(): boolean {
    return this.buffer !== null;
  }

  /** Laad de muziek. Mag mislukken: dan loopt de klok op performance.now. */
  async laad(pad: string, bronStart: number): Promise<void> {
    this.bronStart = bronStart;
    const mijn = this.ronde;
    try {
      const antwoord = await fetch(convertFileSrc(pad));
      if (!antwoord.ok) throw new Error(String(antwoord.status));
      const ruw = await antwoord.arrayBuffer();
      if (mijn !== this.ronde) return;
      const ctx = this.maakCtx();
      const buffer = await ctx.decodeAudioData(ruw);
      if (mijn !== this.ronde) return;
      this.buffer = buffer;
      // Werd er al gespeeld terwijl dit nog laadde? Dan hoort de muziek nu
      // alsnog te beginnen, op de stand waar de tijdlijn inmiddels staat.
      // Zonder dit blijft het stil tot de gebruiker zelf pauzeert en herstart.
      if (this.loopt) this.start(this.tijd());
    } catch {
      // Geen muziek is geen fout — de speler werkt dan op zijn eigen klok.
      if (mijn === this.ronde) this.buffer = null;
    }
  }

  private nu(): number {
    return this.ctx ? this.ctx.currentTime : performance.now() / 1000;
  }

  /** De `AudioContext`, aangemaakt als hij er nog niet is.
   *
   *  Let op de herijking: zonder context loopt de klok op `performance.now()`
   *  en daarna op `ctx.currentTime`. Dat zijn twee verschillende nullen, dus
   *  wie midden in het spelen een context aanmaakt moet de huidige stand eerst
   *  vastleggen — anders springt de tijdlijn naar een willekeurig moment. */
  private maakCtx(): AudioContext {
    if (this.ctx) return this.ctx;
    const t = this.tijd();
    this.ctx = new AudioContext();
    this.vanaf = t;
    this.begin = this.nu();
    return this.ctx;
  }

  /** De tijdlijnpositie in seconden. */
  tijd(): number {
    if (!this.loopt) return this.vanaf;
    return this.vanaf + (this.nu() - this.begin);
  }

  start(vanaf: number): void {
    this.stopBron();
    // Eerst de context (die herijkt op de oude stand), dán de nieuwe stand.
    const ctx = this.maakCtx();
    void ctx.resume();
    this.vanaf = Math.max(0, vanaf);
    this.begin = this.nu();
    this.loopt = true;
    if (this.buffer && this.ctx) {
      const b = this.ctx.createBufferSource();
      b.buffer = this.buffer;
      b.connect(this.ctx.destination);
      // De muziek loopt vanaf hetzelfde punt als de tijdlijn; `bron_start` is
      // waar de montage in het nummer begint (edl.AudioSpoor.bron_start).
      b.start(0, Math.min(this.buffer.duration, this.bronStart + this.vanaf));
      this.bron = b;
    }
  }

  pauzeer(): void {
    if (!this.loopt) return;
    this.vanaf = this.tijd();
    this.loopt = false;
    this.stopBron();
  }

  /** Spring naar een moment. Speelde hij, dan speelt hij daarna door. */
  zoek(t: number): void {
    const speelde = this.loopt;
    this.pauzeer();
    this.vanaf = Math.max(0, t);
    if (speelde) this.start(this.vanaf);
  }

  private stopBron(): void {
    if (!this.bron) return;
    try {
      this.bron.stop();
    } catch {
      // Een bron die al gestopt is gooit; dat is hier geen probleem.
    }
    this.bron.disconnect();
    this.bron = null;
  }

  sluit(): void {
    // Eerst het loopnummer: een `laad()` die nog loopt hoort hierna niets meer
    // aan te maken.
    this.ronde++;
    this.stopBron();
    this.loopt = false;
    void this.ctx?.close();
    this.ctx = null;
    this.buffer = null;
  }
}
