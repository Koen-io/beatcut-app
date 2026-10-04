// Herkaderen: waar valt het venster in de bron?
//
// Dit is de voorvertoningskant van `engine/cve/kader.py` — letterlijk dezelfde
// wiskunde, want anders laat de speler iets anders zien dan de export maakt.
// `tests/kader-gevallen.json` is de afspraak tussen de twee;
// `app/tests/kader.test.ts` en `tests/test_kader.py` lezen die tabel allebei.
//
// Eigen bestand en niet in `uniforms.ts`: daar staat een `?raw`-import van een
// .wgsl-bestand in, en die kan alleen Vite lezen. Zo is de wiskunde los te
// testen met `node --test`.

/** Hoe een bron op het canvas valt: schaal en verschuiving in uv-ruimte.
 *  `uv_bron = uv_canvas * schaal + verschuiving`. */
export type Kader = { schaalX: number; schaalY: number; schuifX: number; schuifY: number };

/** Hoeveel van de bron er in beeld past, als fractie. Nooit meer dan 1 — dat
 *  zou buiten het beeld samplen en een gespiegelde rand geven.
 *  Zelfde functie als `kader.venster()` in engine/cve/kader.py. */
export function venster(bronVerhouding: number, canvasVerhouding: number, zoom = 1): [number, number] {
  const z = Math.max(0.0001, zoom);
  let w = 1 / z;
  let h = 1 / z;
  if (bronVerhouding > canvasVerhouding) w *= canvasVerhouding / bronVerhouding;
  else h *= bronVerhouding / canvasVerhouding;
  return [w, h];
}

/** De linker- of bovenrand van een venster, zodat `punt` het midden is en het
 *  venster binnen de bron blijft. Zelfde als `kader.schuif()` in Python. */
export function schuif(venster: number, punt: number): number {
  const ruimte = Math.max(0, 1 - venster);
  return Math.min(ruimte, Math.max(0, punt - venster / 2));
}

/** "vul": snijd de bron bij tot de canvasverhouding, en zoom met Ken Burns.
 *  `zoom` 1.0 = geen zoom; groter betekent dichterbij.
 *
 *  Twee stappen, in dezelfde volgorde als de export (`render._pasfilter` zet
 *  het kader, `render._zoomfilter` doet de Ken Burns daarbinnen):
 *
 *    1. het kader — een venster op canvasverhouding rond (`kaderX`, `kaderY`);
 *    2. Ken Burns — zoomen en schuiven *binnen* dat venster.
 *
 *  Dat de pan binnen het kader blijft en niet over het hele beeld loopt, is
 *  geen detail: ffmpeg schuift over `groot_b - b` pixels van het al
 *  bijgesneden beeld. Rekende de speler over de volle rest, dan liep een
 *  liggend shot in een staand canvas in de voorvertoning een heel andere kant
 *  op dan in de export. Zie tests/test_kader.py voor de getallen.
 *  Standaard staat het kader in het midden — dan is dit precies wat het was. */
export function kaderVul(
  bronVerhouding: number,
  canvasVerhouding: number,
  zoom: number,
  panX: number,
  panY: number,
  kaderX = 0.5,
  kaderY = 0.5,
): Kader {
  const [w0, h0] = venster(bronVerhouding, canvasVerhouding, 1);
  const x0 = schuif(w0, kaderX);
  const y0 = schuif(h0, kaderY);

  const z = Math.max(0.0001, zoom);
  const w = w0 / z;
  const h = h0 / z;
  const ruimteX = (w0 - w) / 2;
  const ruimteY = (h0 - h) / 2;
  return {
    schaalX: w,
    schaalY: h,
    schuifX: x0 + ruimteX + panX * ruimteX,
    schuifY: y0 + ruimteY + panY * ruimteY,
  };
}

/** Het kaderpunt van een shot op fractie `f` van zijn duur.
 *  Zelfde drie vormen als `kader.punt_op()` in engine/cve/kader.py. */
export type KaderPunt = { x?: number; y?: number; punten?: { t: number; x?: number; y?: number }[] };

export function kaderPuntOp(kader: KaderPunt | null | undefined, f = 0): [number, number] {
  if (!kader) return [0.5, 0.5];
  const punten = kader.punten ?? [];
  if (punten.length === 0) return [kader.x ?? 0.5, kader.y ?? 0.5];

  const g = Math.min(1, Math.max(0, f));
  const rij = punten.map((p) => [p.t, p.x ?? 0.5, p.y ?? 0.5] as [number, number, number]);
  if (g <= rij[0][0]) return [rij[0][1], rij[0][2]];
  for (let i = 0; i + 1 < rij.length; i++) {
    const [t0, x0, y0] = rij[i];
    const [t1, x1, y1] = rij[i + 1];
    if (g <= t1) {
      if (t1 <= t0) return [x0, y0];
      const deel = (g - t0) / (t1 - t0);
      return [x0 + (x1 - x0) * deel, y0 + (y1 - y0) * deel];
    }
  }
  const laatste = rij[rij.length - 1];
  return [laatste[1], laatste[2]];
}

/** "pas": het hele beeld binnen het canvas; uv's buiten 0..1 zijn de balken. */
export function kaderPas(bronVerhouding: number, canvasVerhouding: number): Kader {
  let w = 1;
  let h = 1;
  if (bronVerhouding > canvasVerhouding) h = bronVerhouding / canvasVerhouding;
  else w = canvasVerhouding / bronVerhouding;
  return { schaalX: w, schaalY: h, schuifX: (1 - w) / 2, schuifY: (1 - h) / 2 };
}

