// De veertien overgangen uit `edl.OVERGANGEN` — één bron voor de
// voorvertoning én de export.
//
// Dit bestand stond tot 03-10-2026 in `app/src/speler/` en kon daarom alleen
// in de webview draaien; de export deed de overgangen met `fade`-filters van
// ffmpeg en dat was iets heel anders. Nu leest de speler het hier vandaan
// (`tekenen.ts`) en bakt `compositor/src/gpu.rs` het met `include_str!` in de
// export. Eén bestand, dus geen twee implementaties die uiteenlopen
// (PLAN-v2 §4.4).
//
// Twee functies, en de taakverdeling is scherp:
//
//   overgang_canvas_uv()
//                   — vervorming die mét één monster klaar is. Alleen `pixel`.
//                     Werkt in canvas-uv; de aanroeper rekent de uitkomst naar
//                     de kaders van zijn bronnen en voert ze door
//                     `o_samenstel()`, en zo houdt het de vulmodus (vul / pas
//                     / wazig).
//   overgang_meng() — al het andere. De effecten die er professioneel uit
//                     moeten zien hebben meer dan één monster nodig —
//                     bewegingsonscherpte, straalveeg, kanaalscheiding — en
//                     die halen hun beeld zelf met `o_tap()`.
//
// `o_tap()` werkt in **canvas-uv** en rekent het kader van de bron er zelf in.
// Dat is het hele truukje achter "voorvertoning = export": in de speler zit
// het kaderen (vulmodus plus Ken Burns) in `u.bronA`/`u.bronB`, in de export
// is het al door ffmpeg in het blok gebakken en staat daar de eenheidsmatrix.
// Een zwieper legt in beide gevallen dezelfde afstand af.
//
// Het samenstellen van één bron staat daarom hier en niet in compositor.wgsl:
// `o_samenstel()` is wat de gewone voorvertoning gebruikt én wat `o_tap()`
// gebruikt. Zo houdt een whip_pan, zoom_punch, glitch, slice of rgb_split de
// zwarte balken van vulmodus "pas" en de wazige vulling van "wazig" — vóór
// 03-10-2026 samplede `o_tap()` het beeldvullende kader en verspronk de
// kadering midden in de overgang. De export merkt er niets van: daar staat de
// eenheid plus "vul", en dan is `o_samenstel()` één monster.
//
// Alles is deterministisch uit (frame-index, effectseed) en nooit uit
// `random()`: anders verschillen twee renders van hetzelfde project en kan de
// numpy-tweeling in `tests/ref_compositor.py` de shader niet nameten.

const O_SNEDE      : i32 = 0;
const O_CROSSFADE  : i32 = 1;
const O_DIP_ZWART  : i32 = 2;
const O_DIP_WIT    : i32 = 3;
const O_GLITCH     : i32 = 4;
const O_PIXEL      : i32 = 5;
const O_SLICE      : i32 = 6;
const O_WHIP_PAN   : i32 = 7;
const O_ZOOM_PUNCH : i32 = 8;
const O_WIPE       : i32 = 9;
const O_RADIAAL    : i32 = 10;
const O_FILM_BRAND : i32 = 11;
const O_LICHTLEK   : i32 = 12;
const O_RGB_SPLIT  : i32 = 13;

const PI    : f32 = 3.14159265;
const GAMMA : f32 = 2.2;

// -- deterministische ruis -------------------------------------------------
//
// Een integer-hash en geen `fract(sin(dot(...)) * 43758.5453)`. Dat laatste
// hangt op één ulp na van de `sin` van het platform af, en dan geeft de
// numpy-tweeling andere ruis dan de GPU — de poort meet dan niets meer.
// Zelfde hash als `hash32` in afwerking.wgsl.

fn o_hash(x: u32) -> u32 {
  var v = x;
  v = v ^ (v >> 16u);
  v = v * 2654435769u;
  v = v ^ (v >> 15u);
  v = v * 2246822519u;
  v = v ^ (v >> 16u);
  return v;
}

/// Tussen 0 en 1 uit drie gehele getallen — nooit precies 0 en nooit precies 1.
///
/// Nooit uit pixelcoördinaten: een voorvertoning op 960x540 moet dezelfde
/// ruis geven als de export op 4K. Vandaar dat alles wat hier ingaat een
/// band-, strook- of blokindex is, en geen `x` en `y`.
///
/// **De randen horen er niet bij** (04-10-2026, brein-taak 20261003-181242).
/// `o_hash()` is omkeerbaar, dus hij geeft 0 terug zodra zijn ingang 0 is — en
/// die ingang is 0 bij band 0, as 0, effectseed 0. Dat is geen theoretisch
/// geval: een `edl.json` zonder effectseed valt op 0 terug. Deze ruis is bijna
/// altijd een drempel ("vanaf welke voortgang klapt deze band om"), en een
/// drempel van precies 0 betekent "al omgeklapt vóór de overgang begint",
/// precies 1 "klapt ook op t=1 niet om". `glitch` liet daardoor op het
/// snedeframe al bron B zien in de bovenste band.
///
/// Daarom 23 bits van de hash, een halve stap opgeschoven, gedeeld door 2^23:
/// dan ligt de uitkomst tussen 5,96e-8 en 0,99999994 en nooit op een rand.
/// 23 bits en niet alle 32, omdat een `f32` er maar 24 kan onderscheiden —
/// `f32(0xFFFFFFFFu) + 0.5` rondt af naar precies 2^32 en zou dus alsnog 1,0
/// opleveren. Meegenomen voordeel: `(h >> 9) + 0.5` en de deling door een macht
/// van twee zijn allebei exact in een `f32`, dus de GPU en de numpy-tweeling
/// in `tests/ref_compositor.py` rekenen hier bit voor bit hetzelfde. Daarvóór
/// scheelde de deling door 4294967295 ze een paar 1e-8, en dat kan een drempel
/// de andere kant op duwen — een hele band of blok die omklapt.
fn o_ruis(a: i32, b: i32, c: u32) -> f32 {
  let h = o_hash(
    bitcast<u32>(a) * 374761393u + bitcast<u32>(b) * 668265263u + c * 2147483647u
  );
  return (f32(h >> 9u) + 0.5) / 8388608.0;
}

fn o_frame() -> u32 { return u32(max(0.0, u.klok.y)); }

/// De effectseed uit `edl.json`. Stabiel over de hele overgang — gebruik deze
/// voor "welke band klapt wanneer om", en `o_frame()` erbij voor wat per
/// frame hoort te verschillen.
fn o_seed() -> u32 { return u32(max(0.0, u.klok.z)); }

fn o_verh() -> f32 { return max(0.01, u.klok.w); }

// -- bronnen in canvas-uv --------------------------------------------------

fn o_kader(b: f32) -> vec4<f32> { return select(u.bronA, u.bronB, b > 0.5); }
fn o_paskader(b: f32) -> vec4<f32> { return select(u.pasA, u.pasB, b > 0.5); }

/// De vulmodus van deze bron: 0 = vul, 1 = pas, 2 = wazig.
/// Zie `uniforms.vulmodusNummer`.
fn o_vulmodus(b: f32) -> f32 { return select(u.meng.z, u.meng.w, b > 0.5); }

fn o_naar_bron(b: f32, uv: vec2<f32>) -> vec2<f32> {
  let k = o_kader(b);
  return uv * k.xy + k.zw;
}

/// Hetzelfde, maar met het kader van "pas": het hele beeld binnen het canvas.
fn o_naar_pas(b: f32, uv: vec2<f32>) -> vec2<f32> {
  let k = o_paskader(b);
  return uv * k.xy + k.zw;
}

fn o_binnen(uv: vec2<f32>) -> f32 {
  let s = step(vec2<f32>(0.0), uv) * step(uv, vec2<f32>(1.0));
  return s.x * s.y;
}

/// Eén monster uit bron A (`b` = 0) of B (`b` = 1), op bron-uv.
///
/// Beide texturen worden gesampled en daarna gekozen: `b` komt bij glitch uit
/// een ruisveld en is dus niet uniform, en een `if` daarop zou de keuze van de
/// textuur in niet-uniforme controlestroom zetten.
fn o_monster(b: f32, uv: vec2<f32>) -> vec4<f32> {
  let s = clamp(uv, vec2<f32>(0.0), vec2<f32>(1.0));
  let ca = textureSampleLevel(beeldA, beeldsampler, s, 0.0);
  let cb = textureSampleLevel(beeldB, beeldsampler, s, 0.0);
  return select(ca, cb, b > 0.5);
}

/// Negen taps: de wazige vulling achter een "pas"-beeld. Geen echte gauss —
/// het staat achter het beeld en mag niet duur zijn.
fn o_wazig(b: f32, uv: vec2<f32>) -> vec4<f32> {
  var som = vec4<f32>(0.0);
  let r = 0.018;
  for (var y = -1; y <= 1; y = y + 1) {
    for (var x = -1; x <= 1; x = x + 1) {
      som = som + o_monster(b, uv + vec2<f32>(f32(x), f32(y)) * r);
    }
  }
  return som / 9.0;
}

/// Eén bron samengesteld, met de vulmodus erin verwerkt.
///
/// Buiten het ingepaste beeld hoort bij `pas` zwart en bij `wazig` de wazige
/// vulling — net als `render._pasfilter`, dat voor `pas` `pad=...:black` zet.
/// `modus` komt uit de uniform-buffer en is dus voor het hele beeld gelijk:
/// deze takken zijn uniforme controlestroom, en `o_monster()` samplet met een
/// expliciete LOD en mag daarom overal staan.
fn o_samenstel(b: f32, uvVul: vec2<f32>, uvPas: vec2<f32>, modus: f32) -> vec4<f32> {
  if (modus < 0.5) {
    return o_monster(b, uvVul) * o_binnen(uvVul);
  }
  let c_pas = o_monster(b, uvPas);
  let in_pas = o_binnen(uvPas);
  if (modus < 1.5) {
    return c_pas * in_pas;
  }
  return mix(o_wazig(b, uvVul), c_pas, in_pas);
}

/// Eén monster uit bron A (`b` = 0) of B (`b` = 1), op canvas-uv — met de
/// vulmodus erin, precies zoals de gewone voorvertoning hem samenstelt.
/// Buiten het canvas: zwart — een beeld dat eruit schuift hoort niets achter
/// te laten, geen gespiegelde rand.
fn o_tap(b: f32, uv: vec2<f32>) -> vec4<f32> {
  let c = o_samenstel(b, o_naar_bron(b, uv), o_naar_pas(b, uv), o_vulmodus(b));
  return c * o_binnen(uv);
}

// -- overvloeien in licht --------------------------------------------------
//
// Een `mix()` op sRGB-codes maakt het midden van een overvloei te donker: twee
// beelden van 50 % grijs geven samen 50 %, maar half licht plus half licht is
// 73 % in codes. Een optische printer telde licht op. Vandaar deze omweg.

fn o_lin(c: vec4<f32>) -> vec4<f32> {
  return vec4<f32>(pow(max(c.rgb, vec3<f32>(0.0)), vec3<f32>(GAMMA)), c.a);
}

fn o_srgb(c: vec4<f32>) -> vec4<f32> {
  return vec4<f32>(pow(max(c.rgb, vec3<f32>(0.0)), vec3<f32>(1.0 / GAMMA)), c.a);
}

fn o_meng_licht(a: vec4<f32>, b: vec4<f32>, f: f32) -> vec4<f32> {
  return o_srgb(mix(o_lin(a), o_lin(b), f));
}

// -- het raster van `pixel` ------------------------------------------------

/// Hoeveel blokken breed en hoog het mozaïek van `pixel` nu is. `puls` is
/// `sin(t * PI)`: 0 aan de randen, 1 in het midden.
///
/// Twee plekken hebben hem nodig — `overgang_canvas_uv()` voor het monster en
/// `o_meng()` voor het moment waarop een blok omklapt — en die moeten op
/// hetzelfde raster staan, anders klappen halve blokken om. De numpy-tweeling
/// heeft hem als `_o_raster()`.
fn o_pixelraster(puls: f32) -> vec2<f32> {
  let grof = mix(4096.0, 11.0, puls);
  return vec2<f32>(max(2.0, round(grof * o_verh())), max(2.0, round(grof)));
}

// -- de twee functies die compositor.wgsl aanroept -------------------------

/** Vervorming van de uv's, in **canvas-uv** in en canvas-uv uit.
 *
 *  Alleen `pixel` zit hier: dat is het enige effect waarvoor één monster per
 *  pixel het juiste antwoord is. De rest resampelt meermaals en doet dat in
 *  `overgang_meng()`.
 *
 *  Canvas-uv en niet bron-uv, en dat is het hele punt: de aanroeper rekent de
 *  uitkomst zelf naar élk kader dat hij nodig heeft. In de voorvertoning zijn
 *  dat twee — het vul-kader én het pas-kader — want `o_samenstel()` toont bij
 *  vulmodus `pas` en `wazig` het beeld uit het pas-kader. Tot 04-10-2026
 *  kwantiseerde deze functie alleen het vul-kader, en dan deed het mozaïek in
 *  die twee modi niets: het beeld in beeld bleef haarscherp
 *  (brein-taak 20261003-181243, zelfde familie als de o_tap()-fout hieronder).
 */
fn overgang_canvas_uv(soort: i32, uv: vec2<f32>, t: f32) -> vec2<f32> {
  if (soort != O_PIXEL) {
    return uv;
  }
  // Mozaïek: het raster wordt grof naar het midden toe en weer fijn. Aan de
  // randen zo fijn dat er niets te zien is — op t=0 hoort A ongeschonden in
  // beeld te staan, dat is het snedeframe.
  let raster = o_pixelraster(sin(clamp(t, 0.0, 1.0) * PI));
  return (floor(uv * raster) + vec2<f32>(0.5)) / raster;
}

/** Het eigenlijke mengwerk. Niet zelf aanroepen: `overgang_meng()` hieronder
 *  is de ingang, en die klemt de uitkomst. */
fn o_meng(soort: i32, a: vec4<f32>, b: vec4<f32>, uv: vec2<f32>, t: f32, seed: f32) -> vec4<f32> {
  _ = seed;
  let tt = clamp(t, 0.0, 1.0);
  let puls = sin(tt * PI);   // 0 aan de randen, 1 in het midden
  let frame = o_frame();
  let vast = o_seed();
  let verh = o_verh();

  if (soort == O_SNEDE) {
    return select(a, b, tt >= 1.0);
  }

  if (soort == O_CROSSFADE) {
    return o_meng_licht(a, b, tt);
  }

  if (soort == O_DIP_ZWART) {
    // Eerst dicht, dan open. Niet mengen — dat is het hele punt van een dip.
    let dicht = abs(tt - 0.5) * 2.0;
    let c = mix(a, b, step(0.5, tt));
    // Licht halveren is in codes een factor 0,73; vandaar de gamma.
    return vec4<f32>(c.rgb * pow(dicht, 1.0 / GAMMA), c.a);
  }

  if (soort == O_DIP_WIT) {
    let dicht = abs(tt - 0.5) * 2.0;
    let c = o_lin(mix(a, b, step(0.5, tt)));
    return o_srgb(mix(vec4<f32>(1.0), c, dicht));
  }

  if (soort == O_GLITCH) {
    // Blokverschuiving per band, kanaalscheiding die meeloopt, en af en toe
    // een uitgebrande scheurregel. De keuze A/B staat per band vast over de
    // hele overgang (anders flikkert hij per frame en zie je geen overgang
    // maar ruis); de verschuiving verandert wél per frame.
    let banden = 26.0;
    let band = i32(floor(uv.y * banden));
    // `<` en geen `step()`: omklappen hoort te gebeuren zodra de voortgang de
    // drempel *voorbij* is. Met `step()` klapt een band die op zijn drempel
    // staat al om, en dan hangt het snedeframe af van de ruis. Zo rekent
    // `pixel` hieronder het ook.
    let keuze = select(0.0, 1.0, o_ruis(band, 0, vast) < smoothstep(0.08, 0.92, tt));
    let sprong = (o_ruis(band, 1, frame + vast) - 0.5) * 0.22 * puls;
    let split = 0.016 * puls;
    let p = uv + vec2<f32>(sprong, 0.0);
    let c = vec4<f32>(
      o_tap(keuze, p + vec2<f32>(split, 0.0)).r,
      o_tap(keuze, p).g,
      o_tap(keuze, p - vec2<f32>(split, 0.0)).b,
      1.0,
    );
    let scheur = step(0.965, o_ruis(band, 2, frame + vast)) * puls;
    return mix(c, vec4<f32>(1.0), scheur * 0.75);
  }

  if (soort == O_PIXEL) {
    // Het monster zit al op het raster (`overgang_canvas_uv()`). Hier klapt
    // elk blok op zijn eigen moment om: dat geeft de digitale oplossing in
    // plaats van één harde knip.
    let blok = vec2<i32>(floor(uv * o_pixelraster(puls)));
    return select(a, b, o_ruis(blok.x, blok.y, vast) < smoothstep(0.2, 0.8, tt));
  }

  if (soort == O_SLICE) {
    // Stroken die om en om wegschuiven, elk met een eigen versnelling. Een
    // exponent en geen snelheid: zo komt élke strook op t=1 precies aan.
    let stroken = 13.0;
    let strook = i32(floor(uv.y * stroken));
    let kant = select(-1.0, 1.0, (strook & 1) == 0);
    let macht = 0.7 + 0.7 * o_ruis(strook, 3, vast);
    let e = pow(smoothstep(0.0, 1.0, tt), macht);
    let pa = uv - vec2<f32>(e * kant, 0.0);
    let pb = uv - vec2<f32>((e - 1.0) * kant, 0.0);
    return mix(o_tap(0.0, pa), o_tap(1.0, pb), o_binnen(pb));
  }

  if (soort == O_WHIP_PAN) {
    // Een zwieper, met de onscherpte in de richting van de beweging. De
    // snelheid is de afgeleide van de versnelling, dus de veeg is in het
    // midden het langst en aan de randen nul — daar hoort het beeld scherp.
    let e = smoothstep(0.0, 1.0, tt);
    let veeg = 0.22 * 6.0 * tt * (1.0 - tt);
    var som = vec4<f32>(0.0);
    for (var i = 0; i < 9; i = i + 1) {
      let f = (f32(i) / 8.0 - 0.5) * veeg;
      // A schuift naar links het beeld uit, B komt van rechts binnen.
      som = som
        + o_tap(0.0, uv + vec2<f32>(e + f, 0.0))
        + o_tap(1.0, uv + vec2<f32>(e - 1.0 + f, 0.0));
    }
    return som / 9.0;
  }

  if (soort == O_ZOOM_PUNCH) {
    // A wordt het midden in geduwd, B komt uit een zoom terug. De
    // straalvormige veeg is wat het een punch maakt in plaats van een zoom.
    let e = smoothstep(0.0, 1.0, tt);
    let za = 1.0 + 0.45 * e;
    let zb = 1.0 + 0.45 * (1.0 - e);
    let veeg = 0.10 * 6.0 * tt * (1.0 - tt);
    let m = uv - vec2<f32>(0.5);
    var sa = vec4<f32>(0.0);
    var sb = vec4<f32>(0.0);
    for (var i = 0; i < 7; i = i + 1) {
      let f = 1.0 + (f32(i) / 6.0 - 0.5) * veeg;
      sa = sa + o_tap(0.0, vec2<f32>(0.5) + m / (za * f));
      sb = sb + o_tap(1.0, vec2<f32>(0.5) + m / (zb * f));
    }
    return o_meng_licht(sa / 7.0, sb / 7.0, smoothstep(0.35, 0.65, tt));
  }

  if (soort == O_WIPE) {
    // Zachte rand plus een dun lichtlijntje. Zonder dat ziet een wipe eruit
    // als een jaloezie met trapjes.
    let rand = 0.015;
    let grens = tt * (1.0 + 2.0 * rand) - rand;
    let c = o_meng_licht(b, a, smoothstep(grens - rand, grens + rand, uv.x));
    let lijn = exp(-pow((uv.x - grens) / rand, 2.0));
    return c + vec4<f32>(vec3<f32>(lijn * 0.25), 0.0);
  }

  if (soort == O_RADIAAL) {
    // Klokveeg vanaf twaalf uur, met de klok mee. De verhouding erin, anders
    // staat de naald op een breedbeeldcanvas scheef.
    let d = vec2<f32>((uv.x - 0.5) * verh, uv.y - 0.5);
    let h = fract(atan2(d.x, -d.y) / (2.0 * PI) + 1.0);
    let rand = 0.01;
    let grens = tt * (1.0 + 2.0 * rand) - rand;
    return o_meng_licht(b, a, smoothstep(grens - rand, grens + rand, h));
  }

  if (soort == O_FILM_BRAND) {
    // Een brandvlek die opengaat, met een hete ring eromheen. Het ruisveld
    // hangt aan een raster van 34 cellen hoog en niet aan pixels: zo brandt
    // een 540p-voorvertoning identiek aan een 4K-export.
    let raster = vec2<f32>(round(34.0 * verh), 34.0);
    let g = uv * raster;
    let hoek = floor(g);
    let fr = g - hoek;
    let w = fr * fr * (vec2<f32>(3.0) - 2.0 * fr);
    let hx = i32(hoek.x);
    let hy = i32(hoek.y);
    let n = mix(
      mix(o_ruis(hx, hy, vast), o_ruis(hx + 1, hy, vast), w.x),
      mix(o_ruis(hx, hy + 1, vast), o_ruis(hx + 1, hy + 1, vast), w.x),
      w.y,
    );
    let d = distance(vec2<f32>(uv.x * verh, uv.y), vec2<f32>(0.52 * verh, 0.44));
    let veld = d * 1.25 + (n - 0.5) * 0.30;
    let rand = 0.07;
    let grens = tt * 1.5 - 0.25;
    let c = o_meng_licht(b, a, smoothstep(grens - rand, grens + rand, veld));
    let ring = exp(-pow((veld - grens) / rand, 2.0)) * puls;
    let gloed = mix(vec3<f32>(1.0, 0.52, 0.12), vec3<f32>(1.0, 0.95, 0.80), ring);
    return c + vec4<f32>(gloed * ring * 0.85, 0.0);
  }

  if (soort == O_LICHTLEK) {
    // Een warme lichtbaan die over de snede strijkt en hem in de uitbranding
    // verbergt. Screen en niet optellen: dan blaast het naar wit uit in
    // plaats van naar geel.
    let baan = tt * 1.6 - 0.3;
    let d = (uv.x - baan) * 2.2 - (uv.y - 0.5) * 0.6;
    let kracht = exp(-d * d * 7.0) * puls;
    let c = o_meng_licht(a, b, smoothstep(0.35, 0.65, tt));
    let lek = vec3<f32>(1.0, 0.84, 0.58) * kracht;
    return vec4<f32>(
      vec3<f32>(1.0) - (vec3<f32>(1.0) - c.rgb) * (vec3<f32>(1.0) - lek), c.a
    );
  }

  if (soort == O_RGB_SPLIT) {
    // De kanalen lopen uiteen en komen weer samen; rood loopt voor, blauw na.
    // Een kleine verticale schok erbij, anders is het alleen een schuif.
    let split = 0.035 * puls;
    let schok = (o_ruis(0, i32(frame), vast) - 0.5) * 0.012 * puls;
    let p = uv + vec2<f32>(0.0, schok);
    let f = smoothstep(0.3, 0.7, tt);
    let pr = p + vec2<f32>(split, 0.0);
    let pb = p - vec2<f32>(split, 0.0);
    return vec4<f32>(
      mix(o_tap(0.0, pr).r, o_tap(1.0, pr).r, f),
      mix(o_tap(0.0, p).g,  o_tap(1.0, p).g,  f),
      mix(o_tap(0.0, pb).b, o_tap(1.0, pb).b, f),
      1.0,
    );
  }

  return o_meng_licht(a, b, tt);
}

/** Hoe A (uitgaand) en B (inkomend) in elkaar overgaan. `t` loopt 0..1.
 *
 *  Het antwoord is altijd een weergeefbare kleur: het mengwerk staat in
 *  `o_meng()` en wordt hier op 0..1 geklemd. Dat is geen opsmuk maar een eis —
 *  twee effecten tellen licht óp bij het beeld (het lichtlijntje van `wipe`, de
 *  hete ring van `film_brand`) en komen daarmee boven 1 uit.
 *
 *  Zonder die klem liep de voorvertoning uit de export (gemeten 03-10-2026,
 *  `ontwerp/beatcut2/qa/gouden-frames-overgangen.md`). De export schrijft de
 *  overgang naar een `Rgba8Unorm`-doel en kapt dus af; de voorvertoning houdt
 *  het beeld in `rgba16float` en nam die overwaarde mee naar de look. De
 *  hooglichtdrempel van gloed en halation ziet dan aan de ene kant 1,4 en aan
 *  de andere 1,0 — ΔE2000 tot 6,3, ruim boven de poort van 3. De export had de
 *  klem wel (`clamp()` in `EXPORT_WGSL`), de speler niet; hij stond dus in één
 *  van de twee aansturingen in plaats van in de shader die ze delen.
 */
fn overgang_meng(soort: i32, a: vec4<f32>, b: vec4<f32>, uv: vec2<f32>, t: f32, seed: f32) -> vec4<f32> {
  let c = o_meng(soort, a, b, uv, t, seed);
  return vec4<f32>(clamp(c.rgb, vec3<f32>(0.0), vec3<f32>(1.0)), c.a);
}
