// De uniform-struct van de samenstel-stap, plus de sampler en de twee bronnen.
//
// Eén bestand voor drie kanten: `app/src/speler/uniforms.ts` leest het met
// `?raw` en plakt het vóór de shaders van de speler, en
// `compositor/src/gpu.rs` bakt het met `include_str!` in de overgangspas van
// de export. Zonder dat zou de struct twee keer bestaan en vroeg of laat
// uiteenlopen — en dan is de voorvertoning een andere film dan de export
// (PLAN-v2 §4.4).
//
// Alles is een `vec4<f32>`: elk veld begint op een veelvoud van 16 bytes, dus
// er zijn geen uitlijningsvragen tussen WGSL en de JavaScript-buffer.

struct Uniforms {
  // schaal.xy, verschuiving.xy — "vul" (crop) plus Ken Burns, per bron
  bronA : vec4<f32>,
  bronB : vec4<f32>,
  // idem voor "pas" (letterbox): het hele beeld binnen het canvas
  pasA  : vec4<f32>,
  pasB  : vec4<f32>,
  // x = mengfactor 0..1, y = overgangsoort, z = vulmodus A, w = vulmodus B
  meng  : vec4<f32>,
  // x = tijdlijntijd (s), y = frame-index, z = effectseed, w = canvasverhouding
  klok  : vec4<f32>,
  // x = looksterkte 0..1, y..w vrij voor de look-shader
  look  : vec4<f32>,
  // korrel, halation, gloed, vignet
  afw1  : vec4<f32>,
  // lichtlek, breedbeeld, filmtrilling, kleurrand
  afw2  : vec4<f32>,
}

@group(0) @binding(0) var<uniform> u : Uniforms;
@group(0) @binding(1) var beeldsampler : sampler;
@group(0) @binding(2) var beeldA : texture_2d<f32>;
@group(0) @binding(3) var beeldB : texture_2d<f32>;
