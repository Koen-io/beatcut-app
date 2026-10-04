// `.cube`-bestanden inlezen, in de webview. Tweeling van `compositor/src/lut.rs`.
//
// De tabel gaat als RGBA-viertallen naar de GPU (rood loopt het snelst), want
// `look.wgsl` leest hem als `array<vec4<f32>>` — één bestand voor beide kanten,
// dus ook dezelfde indeling.
//
// Zonder tabel komt er een identiteits-LUT van 2³ terug. Dan rekent de shader
// hetzelfde pad af zonder dat er een tweede codepad voor "geen look" nodig is.

export type Lut = { data: Float32Array; maat: number };

export function identiteit(): Lut {
  const data = new Float32Array(8 * 4);
  let i = 0;
  for (let b = 0; b < 2; b++)
    for (let g = 0; g < 2; g++)
      for (let r = 0; r < 2; r++) {
        data[i++] = r;
        data[i++] = g;
        data[i++] = b;
        data[i++] = 1;
      }
  return { data, maat: 2 };
}

/** Een `.cube` als tekst. Gooit als de maat niet klopt — stil doorgaan met een
 *  halve tabel zou een voorvertoning geven die niet de export is. */
export function leesCube(tekst: string): Lut {
  let maat = 0;
  const waarden: number[] = [];
  for (const ruw of tekst.split("\n")) {
    const regel = ruw.trim();
    if (regel === "" || regel.startsWith("#")) continue;
    if (regel.startsWith("LUT_3D_SIZE")) {
      maat = Number.parseInt(regel.slice("LUT_3D_SIZE".length).trim(), 10);
      continue;
    }
    const eerste = regel[0];
    if (!/[0-9.-]/.test(eerste)) continue; // TITLE, DOMAIN_MIN, DOMAIN_MAX
    const getallen = regel.split(/\s+/).map(Number);
    if (getallen.length === 3 && getallen.every((x) => Number.isFinite(x))) {
      waarden.push(getallen[0], getallen[1], getallen[2], 1);
    }
  }
  if (!Number.isFinite(maat) || maat <= 0) throw new Error("LUT zonder LUT_3D_SIZE");
  const verwacht = maat ** 3;
  if (waarden.length / 4 !== verwacht) {
    throw new Error(`LUT: ${waarden.length / 4} regels, verwacht ${verwacht}`);
  }
  return { data: new Float32Array(waarden), maat };
}
