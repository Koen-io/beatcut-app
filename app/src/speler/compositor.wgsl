// De compositor van de voorvertoning: twee bronbeelden, één canvas.
//
// Wat hier gebeurt, in deze volgorde:
//   1. vertexshader — één quad, en verder niets. Het kaderen (vulmodus plus
//      Ken Burns) stond hier tot 04-10-2026 als transform op de uv's, maar
//      dat kan niet meer: `pixel` vervormt het canvas en daarna moet er nog
//      gekaderd worden, niet ervoor.
//   2. fragmentshader — overgang_canvas_uv() vervormt het canvas,
//      o_naar_bron()/o_naar_pas() uit overgangen.wgsl kaderen, o_samenstel()
//      stelt de bron samen (vulmodus), dan mengt overgang_meng() A en B.
//   3. look() — de kleurbewerking. Staat er een WGSL-bestand in `app/shaders/`
//      dat `fn look(` definieert, dan is dát de look; anders de passthrough
//      onderaan dit bestand. Zie `tekenen.ts`.
//
// `Uniforms`, de sampler en de twee texturen worden door `uniforms.ts`
// gedeclareerd en vóór dit bestand geplakt.

struct Uit {
  @builtin(position) pos : vec4<f32>,
  @location(0) uv   : vec2<f32>,  // canvas-uv, 0..1
}

@vertex
fn vs(@builtin(vertex_index) i : u32) -> Uit {
  // Eén quad als twee driehoeken, zonder vertexbuffer.
  var hoeken = array<vec2<f32>, 4>(
    vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 1.0),
  );
  let uv = hoeken[i];
  var o : Uit;
  o.pos = vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0);
  o.uv = uv;
  return o;
}

// Het samenstellen van één bron (vulmodus vul / pas / wazig) staat in
// `app/shaders/overgangen.wgsl` als `o_samenstel()`. Dáár en niet hier, omdat
// `o_tap()` het ook nodig heeft: de bijzondere overgangen halen hun beeld zelf
// op en moeten dezelfde balken en dezelfde wazige vulling zien als de rest van
// de voorvertoning. Eén functie, dus ze kunnen niet uiteenlopen.

@fragment
fn fs(o : Uit) -> @location(0) vec4<f32> {
  let soort = i32(u.meng.y + 0.5);
  let t = u.meng.x;
  let seed = u.klok.z + u.klok.y;

  // Eerst het canvas vervormen, dan kaderen — en niet andersom. Het mozaïek
  // van `pixel` staat op het canvas, en uit dat ene vervormde punt komen
  // allebei de kaders van allebei de bronnen. Zou je alleen het vul-kader
  // kwantiseren, dan deed het mozaïek niets in vulmodus `pas` en `wazig`:
  // `o_samenstel()` brengt daar het pas-kader in beeld.
  let c = overgang_canvas_uv(soort, o.uv, t);
  let a = o_samenstel(0.0, o_naar_bron(0.0, c), o_naar_pas(0.0, c), u.meng.z);
  let b = o_samenstel(1.0, o_naar_bron(1.0, c), o_naar_pas(1.0, c), u.meng.w);

  var kleur = overgang_meng(soort, a, b, o.uv, t, seed);
  kleur = look(kleur, o.uv);
  return vec4<f32>(kleur.rgb, 1.0);
}
