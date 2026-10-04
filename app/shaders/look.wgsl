// De kleurstap: 3D-LUT met tetraëdrische interpolatie, gemengd op sterkte.
//
// Eén bron voor twee kanten (PLAN-v2 §4.4): de native compositor
// (`compositor/`) en later de live voorvertoning in de webview lezen dit
// bestand allebei letterlijk in. Wijzig je hier iets, dan wijzigt het daar
// allebei mee — dat is de hele reden dat het één bestand is.
//
// De wiskunde is die van `lut3d=interp=tetrahedral` in ffmpeg: de eenheidskubus
// rond het monster wordt in zes tetraëders geknipt, en er wordt alleen met de
// vier hoekpunten van de juiste tetraëder gerekend. Mengen met `sterkte`
// gebeurt in dezelfde ruimte als `looks._meng` het doet: lineair tussen het
// origineel en de volle LUT, in RGB (geen gamma eromheen).

// Alle parameters van de hele keten in één struct. Beide shaderbestanden
// gebruiken dezelfde indeling, zodat er maar één uniform-buffer nodig is.
// 16-byte uitlijning: vier waarden per regel.
struct Params {
    breedte: u32,       // beeldbreedte in pixels
    hoogte: u32,        // beeldhoogte in pixels
    frame: u32,         // frame-index vanaf 0 (korrel en filmtrilling rekenen ermee)
    seed: u32,          // effectseed uit edl.json

    sterkte: f32,       // 0..1, de sterkte-schuif van de look
    lut_grootte: u32,   // 33 voor onze .cube-bestanden
    korrel: f32,        // 0..1
    vignet: f32,        // 0..1

    halation: f32,      // 0..1
    gloed: f32,         // 0..1
    lichtlek: f32,      // 0..1
    breedbeeld: f32,    // 0..1 (schakelaar: >0 is aan)

    filmtrilling: f32,  // 0..1
    kleurrand: f32,     // 0..1
    drempel: f32,       // hooglichtdrempel van de huidige blur-tak (0..1)
    dekking: f32,       // dekking van de huidige screen-blend (0..1)

    mix_r: f32,         // kleurweging na de blur (halation kleurt rood)
    mix_g: f32,
    mix_b: f32,
    straal: u32,        // halve kernelbreedte van de huidige blur-tak
}

@group(0) @binding(0) var<uniform> p: Params;
@group(0) @binding(1) var bron: texture_2d<f32>;
@group(0) @binding(2) var doel: texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var<storage, read> lut: array<vec4<f32>>;

fn lut_op(r: u32, g: u32, b: u32) -> vec3<f32> {
    let n = p.lut_grootte;
    // .cube-volgorde: rood loopt het snelst.
    return lut[(b * n + g) * n + r].rgb;
}

// Tetraëdrische interpolatie, gelijk aan ffmpeg `interp=tetrahedral`.
fn lut_tetra(kleur: vec3<f32>) -> vec3<f32> {
    let n = p.lut_grootte;
    let maxi = n - 1u;
    let s = clamp(kleur, vec3<f32>(0.0), vec3<f32>(1.0)) * f32(maxi);
    let i = min(vec3<u32>(floor(s)), vec3<u32>(maxi - 1u, maxi - 1u, maxi - 1u));
    let d = s - vec3<f32>(f32(i.x), f32(i.y), f32(i.z));

    let c000 = lut_op(i.x,      i.y,      i.z);
    let c111 = lut_op(i.x + 1u, i.y + 1u, i.z + 1u);
    var uit: vec3<f32>;
    if (d.r > d.g) {
        if (d.g > d.b) {
            uit = (1.0 - d.r) * c000 + (d.r - d.g) * lut_op(i.x + 1u, i.y, i.z)
                + (d.g - d.b) * lut_op(i.x + 1u, i.y + 1u, i.z) + d.b * c111;
        } else if (d.r > d.b) {
            uit = (1.0 - d.r) * c000 + (d.r - d.b) * lut_op(i.x + 1u, i.y, i.z)
                + (d.b - d.g) * lut_op(i.x + 1u, i.y, i.z + 1u) + d.g * c111;
        } else {
            uit = (1.0 - d.b) * c000 + (d.b - d.r) * lut_op(i.x, i.y, i.z + 1u)
                + (d.r - d.g) * lut_op(i.x + 1u, i.y, i.z + 1u) + d.g * c111;
        }
    } else {
        if (d.b > d.g) {
            uit = (1.0 - d.b) * c000 + (d.b - d.g) * lut_op(i.x, i.y, i.z + 1u)
                + (d.g - d.r) * lut_op(i.x, i.y + 1u, i.z + 1u) + d.r * c111;
        } else if (d.b > d.r) {
            uit = (1.0 - d.g) * c000 + (d.g - d.b) * lut_op(i.x, i.y + 1u, i.z)
                + (d.b - d.r) * lut_op(i.x, i.y + 1u, i.z + 1u) + d.r * c111;
        } else {
            uit = (1.0 - d.g) * c000 + (d.g - d.r) * lut_op(i.x, i.y + 1u, i.z)
                + (d.r - d.b) * lut_op(i.x + 1u, i.y + 1u, i.z) + d.b * c111;
        }
    }
    return uit;
}

@compute @workgroup_size(8, 8, 1)
fn look(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= p.breedte || gid.y >= p.hoogte) { return; }
    let xy = vec2<i32>(i32(gid.x), i32(gid.y));
    let in_kleur = textureLoad(bron, xy, 0);
    let na = lut_tetra(in_kleur.rgb);
    let uit = mix(in_kleur.rgb, na, p.sterkte);
    textureStore(doel, xy, vec4<f32>(uit, in_kleur.a));
}
