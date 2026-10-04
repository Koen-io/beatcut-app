// De afwerking: korrel, vignet, halation, gloed, lichtlek, filmtrilling en
// kleurrand. Zelfde bestand voor de export en voor de live voorvertoning.
//
// Twee dingen die hier bewust anders zijn dan in een los effect:
//
// 1. **Alle maten zijn een fractie van de beeldhoogte**, nooit pixels. Anders
//    is de gloed op een 540p-proxy twee keer zo breed als op de export, en dan
//    is de voorvertoning niet meer dezelfde film (PLAN-v2 §4.4).
// 2. **Korrel en filmtrilling zijn deterministisch** uit (x, y, frame-index,
//    seed). Geen `random()`: dan zouden twee renders van hetzelfde project
//    verschillen en is de gouden-frames-poort zinloos.
//
// De volgorde is die van `render._lookfilter`: eerst de kleur (look.wgsl), dan
// het licht (gloed, halation, lichtlek), dan het materiaal (korrel, vignet,
// kleurrand), dan de camera (filmtrilling) en als laatste de balken.

struct Params {
    breedte: u32,
    hoogte: u32,
    frame: u32,
    seed: u32,

    sterkte: f32,
    lut_grootte: u32,
    korrel: f32,
    vignet: f32,

    halation: f32,
    gloed: f32,
    lichtlek: f32,
    breedbeeld: f32,

    filmtrilling: f32,
    kleurrand: f32,
    drempel: f32,
    dekking: f32,

    mix_r: f32,
    mix_g: f32,
    mix_b: f32,
    straal: u32,
}

@group(0) @binding(0) var<uniform> p: Params;
@group(0) @binding(1) var bron: texture_2d<f32>;
@group(0) @binding(2) var doel: texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var<storage, read> kernel: array<f32>;
@group(0) @binding(4) var tweede: texture_2d<f32>;   // de tak die erover gemengd wordt

fn klem_xy(x: i32, y: i32) -> vec2<i32> {
    return vec2<i32>(clamp(x, 0, i32(p.breedte) - 1), clamp(y, 0, i32(p.hoogte) - 1));
}

// -- hooglichten -----------------------------------------------------------
// Alleen wat helderder is dan de drempel blijft staan, de rest wordt zwart.
// Gloed en halation komen in het echt uit de hooglichten; zonder deze stap
// licht het hele beeld op en lijkt het op een vuile lens.
//
// De overgang is een band van vier eenheden breed en geen harde grens. Dat is
// niet voor de schoonheid: met een harde grens kiepert een pixel die er tot op
// de laatste bit tegenaan ligt bij de kleinste rekenafwijking helemaal om, en
// de blur smeert dat verschil daarna over zijn hele straal uit. Gemeten
// 03-10-2026: tot 6/255 verschil tussen GPU en de numpy-referentie, genoeg om
// de gouden-frames-poort te laten vallen. Met een band is het verschil
// evenredig aan de afwijking in plaats van alles-of-niets.
const HOOGLICHT_BAND: f32 = 4.0 / 255.0;

@compute @workgroup_size(8, 8, 1)
fn hooglichten(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let c = textureLoad(bron, xy, 0);
    let m = smoothstep(vec3<f32>(p.drempel), vec3<f32>(p.drempel + HOOGLICHT_BAND), c.rgb);
    textureStore(doel, xy, vec4<f32>(c.rgb * m, 1.0));
}

// -- gaussische vervaging, gescheiden in twee passen ----------------------
// De kernel komt kant-en-klaar uit de buffer (zelfde getallen in de numpy-
// referentie), randen worden vastgeklemd. Geen IIR-benadering zoals ffmpeg
// `gblur`: een expliciete kernel is in beide implementaties exact hetzelfde.
fn vervaag(gid: vec3<u32>, dx: i32, dy: i32) {
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let r = i32(p.straal);
    var som = vec3<f32>(0.0);
    for (var k: i32 = -r; k <= r; k = k + 1) {
        let w = kernel[u32(k + r)];
        som = som + w * textureLoad(bron, klem_xy(xy.x + k * dx, xy.y + k * dy), 0).rgb;
    }
    textureStore(doel, xy, vec4<f32>(som, 1.0));
}

@compute @workgroup_size(8, 8, 1)
fn vervaag_h(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    vervaag(gid, 1, 0);
}

@compute @workgroup_size(8, 8, 1)
fn vervaag_v(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let r = i32(p.straal);
    var som = vec3<f32>(0.0);
    for (var k: i32 = -r; k <= r; k = k + 1) {
        som = som + kernel[u32(k + r)] * textureLoad(bron, klem_xy(xy.x, xy.y + k), 0).rgb;
    }
    // De kleurweging hoort ná de blur: halation is rood, niet wit.
    som = som * vec3<f32>(p.mix_r, p.mix_g, p.mix_b);
    textureStore(doel, xy, vec4<f32>(som, 1.0));
}

// -- screen-blend ----------------------------------------------------------
// `blend=all_mode=screen:all_opacity=o` weegt bij elke modus behalve `normal`
// naar het resultaat van de blend: boven + (blend - boven) * o.
@compute @workgroup_size(8, 8, 1)
fn screen_meng(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let a = textureLoad(bron, xy, 0);
    let b = textureLoad(tweede, xy, 0).rgb;
    let s = vec3<f32>(1.0) - (vec3<f32>(1.0) - a.rgb) * (vec3<f32>(1.0) - b);
    textureStore(doel, xy, vec4<f32>(a.rgb + (s - a.rgb) * p.dekking, a.a));
}

// -- deterministische ruis -------------------------------------------------
fn hash32(x: u32) -> u32 {
    var v = x;
    v = v ^ (v >> 16u);
    v = v * 2654435769u;
    v = v ^ (v >> 15u);
    v = v * 2246822519u;
    v = v ^ (v >> 16u);
    return v;
}

fn ruis(x: u32, y: u32) -> f32 {
    let h = hash32(x * 374761393u + y * 668265263u + p.frame * 2147483647u + p.seed * 362437u);
    return f32(h) / 4294967295.0 * 2.0 - 1.0;   // -1 .. 1
}

// -- lichtlek, korrel, vignet ---------------------------------------------
@compute @workgroup_size(8, 8, 1)
fn materiaal(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let b = f32(p.breedte);
    let h = f32(p.hoogte);
    var c = textureLoad(bron, xy, 0);
    var kleur = c.rgb;

    // Lichtlek: een warme wash uit de linkerbovenhoek, analytisch in plaats van
    // een vervaagde gradiënt — hij is al glad, vervagen verandert hem niet.
    if (p.lichtlek > 0.0) {
        let u = f32(gid.x) / b;
        let v = f32(gid.y) / h;
        let afstand = clamp(1.0 - sqrt(u * u + v * v) / 1.41421356, 0.0, 1.0);
        let lek = afstand * afstand * vec3<f32>(1.0, 0.58, 0.22);
        let s = vec3<f32>(1.0) - (vec3<f32>(1.0) - kleur) * (vec3<f32>(1.0) - lek);
        kleur = kleur + (s - kleur) * (0.55 * p.lichtlek);
    }

    // Korrel: kracht in dezelfde schaal als ffmpeg `noise=alls=` (0..255).
    if (p.korrel > 0.0) {
        let kracht = max(1.0, round(2.0 + 22.0 * p.korrel)) / 255.0;
        kleur = kleur + vec3<f32>(ruis(gid.x, gid.y)) * kracht;
    }

    // Vignet: cos⁴ van de hoek, met de hoek uit de schuif.
    if (p.vignet > 0.0) {
        let hoek = 0.20 + 1.00 * p.vignet;
        let dx = (f32(gid.x) + 0.5) / b - 0.5;
        let dy = (f32(gid.y) + 0.5) / h - 0.5;
        let r = sqrt(dx * dx + dy * dy) / 0.70710678;
        let f = pow(max(cos(hoek * r), 0.0), 4.0);
        kleur = kleur * f;
    }

    textureStore(doel, xy, vec4<f32>(clamp(kleur, vec3<f32>(0.0), vec3<f32>(1.0)), c.a));
}

// -- camera: kleurrand, filmtrilling, breedbeeld ---------------------------
// Alle drie hersamplen, dus ze zitten in één pas: de coördinaat van de
// trilling gaat er eerst doorheen, de kleurrand schuift daarna per kanaal.
fn bilineair(u: f32, v: f32) -> vec3<f32> {
    let x0 = floor(u);
    let y0 = floor(v);
    let fx = u - x0;
    let fy = v - y0;
    let a = textureLoad(bron, klem_xy(i32(x0),      i32(y0)),      0).rgb;
    let b = textureLoad(bron, klem_xy(i32(x0) + 1,  i32(y0)),      0).rgb;
    let c = textureLoad(bron, klem_xy(i32(x0),      i32(y0) + 1),  0).rgb;
    let d = textureLoad(bron, klem_xy(i32(x0) + 1,  i32(y0) + 1),  0).rgb;
    return mix(mix(a, b, fx), mix(c, d, fx), fy);
}

@compute @workgroup_size(8, 8, 1)
fn camera(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let b = f32(p.breedte);
    let h = f32(p.hoogte);
    var u = f32(gid.x);
    var v = f32(gid.y);

    if (p.filmtrilling > 0.0) {
        // Twee sinussen met onvergelijkbare perioden: ziet er net zo onrustig
        // uit als ruis en is exact herhaalbaar. Zelfde opzet als in ffmpeg:
        // beeld opschalen met 2*amp en er een bewegend venster uit halen.
        let amp = max(1.0, round(0.003 * h * p.filmtrilling));
        let fx = 1.9 + f32(p.seed % 7u) * 0.11;
        let fy = 1.31 + f32(p.seed % 5u) * 0.09;
        let n = f32(p.frame);
        u = (u + amp + amp * sin(n * fx)) * (b / (b + 2.0 * amp));
        v = (v + amp + amp * sin(n * fy)) * (h / (h + 2.0 * amp));
    }

    var kleur: vec3<f32>;
    if (p.kleurrand > 0.0) {
        let px = max(1.0, round(0.0015 * b * p.kleurrand));
        kleur = vec3<f32>(
            bilineair(u - px, v).r,
            bilineair(u, v).g,
            bilineair(u + px, v).b,
        );
    } else {
        kleur = bilineair(u, v);
    }

    if (p.breedbeeld > 0.0) {
        // 2.39:1-balken, even hoogte zodat de band gecentreerd blijft.
        let doelh = f32((i32(b / 2.39) / 2) * 2);
        if (doelh > 0.0 && doelh < h) {
            let boven = floor((h - doelh) / 2.0);
            let yy = f32(gid.y);
            if (yy < boven || yy >= boven + doelh) { kleur = vec3<f32>(0.0); }
        }
    }

    textureStore(doel, xy, vec4<f32>(clamp(kleur, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0));
}
