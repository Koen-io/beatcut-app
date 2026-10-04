// `struct Params` uit app/shaders/*.wgsl, aan de kant van de webview.
//
// Tweeling van `Params` in `compositor/src/main.rs`: twintig velden van vier
// bytes, in exact die volgorde. Verandert de struct in de shader, dan moet het
// hier mee — vandaar dat de velden hieronder dezelfde namen hebben.

/** De drempels van de twee blur-takken, net als in `compositor/src/gpu.rs`. */
export const HOOGLICHT_GLOED = 185 / 255;
export const HOOGLICHT_HALATION = 205 / 255;

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

export const GEEN_AFWERKING: Afwerking = {
  korrel: 0, halation: 0, gloed: 0, vignet: 0,
  lichtlek: 0, breedbeeld: 0, filmtrilling: 0, kleurrand: 0,
};

/** De acht waarden in de volgorde van `edl.Afwerking`. */
export function afwerkingUitLijst(a: readonly number[]): Afwerking {
  return {
    korrel: a[0] ?? 0,
    halation: a[1] ?? 0,
    gloed: a[2] ?? 0,
    vignet: a[3] ?? 0,
    lichtlek: a[4] ?? 0,
    breedbeeld: a[5] ?? 0,
    filmtrilling: a[6] ?? 0,
    kleurrand: a[7] ?? 0,
  };
}

export function heeftAfwerking(a: Afwerking): boolean {
  return Object.values(a).some((x) => x > 0);
}

export type Velden = {
  breedte: number;
  hoogte: number;
  frame: number;
  seed: number;
  sterkte: number;
  lutGrootte: number;
  afwerking: Afwerking;
  drempel?: number;
  dekking?: number;
  mix?: readonly [number, number, number];
  straal?: number;
};

export const PARAMS_BYTES = 80;

/** De twintig velden als 80 bytes, klaar voor `writeBuffer`. */
export function schrijfParams(v: Velden, doel = new ArrayBuffer(PARAMS_BYTES)): ArrayBuffer {
  const u = new Uint32Array(doel);
  const f = new Float32Array(doel);
  const a = v.afwerking;
  u[0] = v.breedte;
  u[1] = v.hoogte;
  u[2] = v.frame >>> 0;
  u[3] = v.seed >>> 0;
  f[4] = Math.min(1, Math.max(0, v.sterkte));
  u[5] = v.lutGrootte;
  f[6] = a.korrel;
  f[7] = a.vignet;
  f[8] = a.halation;
  f[9] = a.gloed;
  f[10] = a.lichtlek;
  f[11] = a.breedbeeld;
  f[12] = a.filmtrilling;
  f[13] = a.kleurrand;
  f[14] = v.drempel ?? 0;
  f[15] = v.dekking ?? 0;
  f[16] = v.mix?.[0] ?? 1;
  f[17] = v.mix?.[1] ?? 1;
  f[18] = v.mix?.[2] ?? 1;
  u[19] = v.straal ?? 0;
  return doel;
}

/** Gaussische kernel met expliciete straal, genormaliseerd op 1.
 *  Letterlijk `kernel()` uit `compositor/src/main.rs` — geen IIR-benadering,
 *  want alleen expliciete gewichten zijn aan beide kanten dezelfde getallen. */
export function kernel(sigma: number): Float32Array {
  const straal = Math.min(64, Math.max(1, Math.ceil(3 * sigma)));
  const w = new Float32Array(2 * straal + 1);
  let som = 0;
  for (let k = -straal; k <= straal; k++) {
    const x = Math.exp(-(k * k) / (2 * sigma * sigma));
    w[k + straal] = x;
    som += x;
  }
  for (let i = 0; i < w.length; i++) w[i] /= som;
  return w;
}

/** Half-precision terug naar f32. Zelfde aanpak als `f16_naar_f32` in
 *  `compositor/src/gpu.rs`: rekenen in plaats van in bits schuiven, want
 *  subnormale halfs (een donker beeld zit er vol mee) gingen daar mis. */
export function f16NaarF32(h: number): number {
  const teken = h & 0x8000 ? -1 : 1;
  const exp = (h >> 10) & 0x1f;
  const mant = h & 0x3ff;
  if (exp === 0) return teken * mant * 5.9604645e-8;
  if (exp === 31) return teken * Infinity;
  return teken * (1 + mant / 1024) * 2 ** (exp - 15);
}
