// De ingebouwde look: hij doet niets.
//
// Zodra er in `app/shaders/` een WGSL-bestand staat dat `fn look(` definieert,
// gebruikt `tekenen.ts` dát bestand in plaats van dit. Zo kan de speler nu al
// afspelen terwijl de echte look-shaders nog gebouwd worden, en hoeft er later
// niets in de speler te veranderen om ze aan te sluiten — zie PLAN-v2.md §4.4.
//
// Het contract is één functie:
//     fn look(kleur: vec4<f32>, uv: vec2<f32>) -> vec4<f32>
// met `u` (de Uniforms uit uniforms.ts) als enige andere invoer. `u.look.x` is
// de sterkte, `u.afw1`/`u.afw2` de afwerking, `u.klok.y` de frame-index en
// `u.klok.z` de effectseed — ruis dus altijd daaruit, nooit random.

fn look(kleur: vec4<f32>, uv: vec2<f32>) -> vec4<f32> {
  _ = uv;
  return kleur;
}
