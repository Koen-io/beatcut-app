// Een geheugen van ingelezen proxies met een plafond.
//
// Tot 13-10-2026 hield de speler élke proxy vast die ooit geladen was. Bij
// een montage over 21 clips is dat een paar honderd MB; bij 100 clips loopt
// het in de gigabytes, en de webview valt dan stil. Nu: minst recent gebruikt
// eruit zodra het plafond (bytes of aantal) overschreden wordt — maar nooit
// een proxy die nog in gebruik is (`vast`): daar hangt een decoder aan.
//
// Pure klasse, zonder browser: app/tests/proxycache.test.ts toetst hem.

export type MetBytes = { bytes: number };

export class ProxyCache<T extends MetBytes> {
  private readonly rij = new Map<string, { belofte: Promise<T>; bytes: number }>();
  readonly maxBytes: number;
  readonly maxAantal: number;

  // Geen parameter-properties: node --test leest TypeScript in strip-only
  // mode en kent die syntaxis niet.
  constructor(maxBytes: number, maxAantal: number) {
    this.maxBytes = maxBytes;
    this.maxAantal = maxAantal;
  }

  /** De proxy voor dit pad; `lees` wordt alleen geroepen als hij er niet is.
   *  `vast` zijn de paden die nu niet weg mogen (huidig, vorig, volgend blok). */
  haal(pad: string, lees: () => Promise<T>, vast: ReadonlySet<string> = new Set()): Promise<T> {
    const bestaand = this.rij.get(pad);
    if (bestaand) {
      // Opnieuw achteraan zetten: Map houdt invoegvolgorde, dus vooraan is oudst.
      this.rij.delete(pad);
      this.rij.set(pad, bestaand);
      return bestaand.belofte;
    }
    const belofte = lees();
    const rij = { belofte, bytes: 0 };
    this.rij.set(pad, rij);
    // Wat net gevraagd is staat zelf ook vast: anders kon een plafond van
    // één de proxy opruimen vóór de decoder hem had.
    const beschermd = new Set(vast);
    beschermd.add(pad);
    void belofte.then(
      (p) => {
        if (this.rij.get(pad) === rij) {
          rij.bytes = p.bytes;
          this.ruimOp(beschermd);
        }
      },
      () => {
        // Mislukt: niet onthouden, anders blijft de fout voor altijd staan.
        if (this.rij.get(pad) === rij) this.rij.delete(pad);
      },
    );
    this.ruimOp(beschermd);
    return belofte;
  }

  /** Gooi de oudste eruit tot we onder de plafonds zitten. */
  ruimOp(vast: ReadonlySet<string>): string[] {
    const weg: string[] = [];
    let bytes = this.totaalBytes();
    for (const [pad, r] of this.rij) {
      if (this.rij.size - weg.length <= this.maxAantal && bytes <= this.maxBytes) break;
      if (vast.has(pad)) continue;
      weg.push(pad);
      bytes -= r.bytes;
    }
    for (const pad of weg) this.rij.delete(pad);
    return weg;
  }

  totaalBytes(): number {
    let n = 0;
    for (const r of this.rij.values()) n += r.bytes;
    return n;
  }

  get aantal(): number {
    return this.rij.size;
  }

  heeft(pad: string): boolean {
    return this.rij.has(pad);
  }

  leeg(): void {
    this.rij.clear();
  }
}
