// De uniform-struct van de compositor — één bron van waarheid voor WGSL en TS.
//
// Waarom een eigen bestand: PLAN-v2.md §4.4 zegt dat de look-shaders in
// `app/shaders/` voor preview én export letterlijk hetzelfde zijn. Die shaders
// moeten dus weten hoe de uniform-buffer eruitziet zonder dat ze de speler
// kennen. Alles is een `vec4<f32>`, zodat er geen uitlijningsvragen zijn: elk
// veld begint op een veelvoud van 16 bytes, in WGSL en in deze buffer.
//
// Verandert de struct, dan verandert `WGSL_UNIFORMS` mee — dat is de tekst die
// de shader zelf gebruikt, dus een veld toevoegen kan niet half.

import uniformsWgsl from "../../shaders/uniforms.wgsl?raw";

/** Negen vec4's van 4 floats. */
export const VELDEN = 9;
export const BYTES = VELDEN * 16;

/** De WGSL-declaratie. De compositor plakt dit vóór de shaderbronnen.
 *
 *  Komt uit `app/shaders/uniforms.wgsl`, hetzelfde bestand dat `gpu.rs` met
 *  `include_str!` in de export bakt — anders bestaat de struct twee keer. */
export const WGSL_UNIFORMS = uniformsWgsl;

/** Vulmodus zoals `edl.VideoBlok.vulmodus`, als getal voor de shader.
 *
 *  Drie aparte waarden, want de drie modi geven drie andere beelden:
 *  0 = vul (vergroten en wegsnijden), 1 = pas (inpassen met zwarte balken),
 *  2 = wazig (inpassen, balken gevuld met een uitvergroot wazig beeld).
 *  `pas` en `wazig` samen laten vallen gaf in de voorvertoning wazige vulling
 *  waar de export zwarte balken rendert (`render._pasfilter`, `pad=...:black`).
 */
export function vulmodusNummer(modus: string): number {
  if (modus === "vul") return 0;
  return modus === "wazig" ? 2 : 1;
}

/** De overgangen uit `edl.OVERGANGEN`, in dezelfde volgorde — de shader kiest
 *  op deze index. Een naam die hier niet in staat wordt een snede, en dat is
 *  precies waarom de lijst in edl.py een vaste tuple is. */
export const OVERGANGEN = [
  "snede",
  "crossfade",
  "dip_zwart",
  "dip_wit",
  "glitch",
  "pixel",
  "slice",
  "whip_pan",
  "zoom_punch",
  "wipe",
  "radiaal",
  "film_brand",
  "lichtlek",
  "rgb_split",
] as const;

export function overgangNummer(soort: string): number {
  const i = (OVERGANGEN as readonly string[]).indexOf(soort);
  return i < 0 ? 0 : i;
}

/** Hoe een bron op het canvas valt: schaal en verschuiving in uv-ruimte.
 *  `uv_bron = uv_canvas * schaal + verschuiving`. */
export type Kader = { schaalX: number; schaalY: number; schuifX: number; schuifY: number };

/** "vul": snijd de bron bij tot de canvasverhouding, en zoom met Ken Burns.
 *  `zoom` 1.0 = geen zoom; groter betekent dichterbij. */
export function kaderVul(bronVerhouding: number, canvasVerhouding: number, zoom: number, panX: number, panY: number): Kader {
  // Hoeveel van de bron past er in beeld? Nooit meer dan 1 — dat zou buiten
  // het beeld samplen en een gespiegelde rand geven.
  let z = Math.max(0.0001, zoom);
  let w = 1 / z;
  let h = 1 / z;
  if (bronVerhouding > canvasVerhouding) w *= canvasVerhouding / bronVerhouding;
  else h *= bronVerhouding / canvasVerhouding;
  // Het pan-bereik is wat er overblijft naast het zichtbare venster.
  const ruimteX = (1 - w) / 2;
  const ruimteY = (1 - h) / 2;
  return {
    schaalX: w,
    schaalY: h,
    schuifX: ruimteX + panX * ruimteX,
    schuifY: ruimteY + panY * ruimteY,
  };
}

/** "pas": het hele beeld binnen het canvas; uv's buiten 0..1 zijn de balken. */
export function kaderPas(bronVerhouding: number, canvasVerhouding: number): Kader {
  let w = 1;
  let h = 1;
  if (bronVerhouding > canvasVerhouding) h = bronVerhouding / canvasVerhouding;
  else w = canvasVerhouding / bronVerhouding;
  return { schaalX: w, schaalY: h, schuifX: (1 - w) / 2, schuifY: (1 - h) / 2 };
}

export type Stand = {
  kaderA: Kader;
  kaderB: Kader;
  pasA: Kader;
  pasB: Kader;
  meng: number;
  overgang: number;
  vulmodusA: number;
  vulmodusB: number;
  tijd: number;
  frame: number;
  seed: number;
  canvasVerhouding: number;
  looksterkte: number;
  afwerking: number[]; // acht waarden, in de volgorde van edl.Afwerking
};

/** Zet een stand om in de 36 floats die de GPU verwacht. */
export function schrijfUniforms(s: Stand, uit = new Float32Array(VELDEN * 4)): Float32Array {
  const kader = (k: Kader, op: number) => {
    uit[op] = k.schaalX;
    uit[op + 1] = k.schaalY;
    uit[op + 2] = k.schuifX;
    uit[op + 3] = k.schuifY;
  };
  kader(s.kaderA, 0);
  kader(s.kaderB, 4);
  kader(s.pasA, 8);
  kader(s.pasB, 12);
  uit.set([s.meng, s.overgang, s.vulmodusA, s.vulmodusB], 16);
  uit.set([s.tijd, s.frame, s.seed, s.canvasVerhouding], 20);
  uit.set([s.looksterkte, 0, 0, 0], 24);
  const a = s.afwerking;
  uit.set([a[0] ?? 0, a[1] ?? 0, a[2] ?? 0, a[3] ?? 0], 28);
  uit.set([a[4] ?? 0, a[5] ?? 0, a[6] ?? 0, a[7] ?? 0], 32);
  return uit;
}
