"""Maakt de 24 BeatCut-looks als eigen 3D-LUTs (.cube, 33³).

Alle kleurwiskunde is hier zelf geschreven: geen bestaande LUT-pakketten, dus
de looks zijn van ons en mogen in de app mee. Werkt op beeldwaarden zoals ze
in de video staan (Rec.709, gamma-gecodeerd, 0..1) — precies wat ffmpeg
`lut3d` en een WebGL-3D-textuur ook krijgen.

    python maak_looks.py <uitmap>            → <uitmap>/<id>.cube + looks.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

N = 33
LUMA = np.array([0.2126, 0.7152, 0.0722])


# ---------------------------------------------------------------- bouwstenen
def luma(c):
    return (c * LUMA).sum(-1, keepdims=True)


def mix(a, b, t):
    return a + (b - a) * t


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def contrast(c, k, pivot=0.45):
    """S-curve rond pivot; k>1 meer contrast. Behoudt 0 en 1."""
    x = np.clip(c, 0, 1)
    lo = pivot * (x / pivot) ** k
    hi = 1 - (1 - pivot) * ((1 - x) / (1 - pivot)) ** k
    return np.where(x < pivot, lo, hi)


def saturatie(c, s):
    y = luma(c)
    return y + (c - y) * s


def wit(c, temp=0.0, tint=0.0):
    """temp>0 warmer, tint>0 magenta. Kleine waarden (±0.1)."""
    g = np.array([1 + temp * 0.6, 1 - tint * 0.5, 1 - temp * 0.6]) * np.array([1, 1 + 0 * tint, 1])
    g = g * np.array([1 + tint * 0.25, 1, 1 + tint * 0.25])
    return c * g


def lift_gain(c, lift=0.0, gain=1.0, gamma=1.0):
    c = np.clip(c, 0, 1) ** (1 / gamma)
    return lift + c * (gain - lift)


def split(c, schaduw, licht, sterkte=1.0, balans=0.5):
    """Split-toning: kleur in de schaduwen en in de hoge lichten."""
    y = luma(c)
    ws = (1 - smooth(0.0, balans + 0.15, y)) * sterkte
    wl = smooth(balans - 0.15, 1.0, y) * sterkte
    return c + ws * (np.array(schaduw) - 0.5) * 0.5 + wl * (np.array(licht) - 0.5) * 0.5


def schouder(c, start=0.75):
    """Zachte afronding van de hoge lichten, zoals film."""
    x = np.clip(c, 0, 1.5)
    boven = start + (1 - start) * np.tanh((x - start) / (1 - start))
    return np.where(x > start, boven, x)


def zwartwit(c, mixer=(0.30, 0.59, 0.11)):
    y = (c * np.array(mixer)).sum(-1, keepdims=True)
    return np.repeat(y, 3, -1)


def huid_naar(c, doel=(1.0, 0.62, 0.42), kracht=0.25):
    """Trek warme middentonen (huid) iets naar een doelkleur."""
    r, g, b = c[..., 0:1], c[..., 1:2], c[..., 2:3]
    warm = np.clip((r - b) * 2.2, 0, 1) * smooth(0.15, 0.45, luma(c)) * (1 - smooth(0.7, 0.95, luma(c)))
    doelc = luma(c) * np.array(doel) / (np.array(doel) * LUMA).sum()
    return mix(c, doelc, warm * kracht)


def kleur_sat(c, tint_hue, s, breedte=0.12):
    """Verzadiging per tint (0..1 = rood..rood). s>1 meer, <1 minder."""
    mx, mn = c.max(-1, keepdims=True), c.min(-1, keepdims=True)
    d = mx - mn + 1e-6
    r, g, b = c[..., 0:1], c[..., 1:2], c[..., 2:3]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6
    afst = np.minimum(np.abs(h - tint_hue), 1 - np.abs(h - tint_hue))
    w = (1 - smooth(0, breedte, afst)) * np.clip(d * 3, 0, 1)
    return mix(c, saturatie(c, s), w)


# ---------------------------------------------------------------- de looks
def L(f):
    return f


LOOKS = [
    # id, naam, sfeer, functie, afwerking (korrel, halation, gloed, vignet, lichtlek) 0..100
    ("origineel", "Origineel", "", lambda c: c, (0, 0, 0, 0, 0)),
    ("blockbuster", "Blockbuster", "Cinematisch",
     lambda c: schouder(huid_naar(split(contrast(saturatie(c, 1.08), 1.25), (0.25, 0.55, 0.62), (0.68, 0.52, 0.36), 0.9), (1, .6, .4), .3)),
     (15, 20, 15, 35, 0)),
    ("neonnacht", "Neonnacht", "Cinematisch",
     lambda c: schouder(split(contrast(saturatie(lift_gain(c, 0.0, 0.92), 1.35), 1.35), (0.30, 0.45, 0.75), (0.78, 0.40, 0.70), 1.0)),
     (20, 35, 40, 45, 0)),
    ("bioscoop", "Bioscoop 250", "Cinematisch",
     lambda c: schouder(split(lift_gain(contrast(saturatie(c, 0.88), 1.12), 0.035, 0.97), (0.40, 0.55, 0.52), (0.62, 0.55, 0.45), 0.6), 0.7),
     (25, 25, 20, 30, 0)),
    ("woestijn", "Woestijn", "Cinematisch",
     lambda c: schouder(contrast(wit(saturatie(c, 0.82), 0.10, 0.02), 1.18)),
     (15, 10, 20, 35, 0)),
    ("portret", "Portret 400", "Analoge film",
     lambda c: schouder(huid_naar(split(lift_gain(contrast(saturatie(c, 0.9), 0.95), 0.03, 1.0, 1.05), (0.48, 0.52, 0.55), (0.56, 0.52, 0.47), 0.6), (1, .66, .5), .25), 0.72),
     (25, 10, 10, 20, 0)),
    ("landschap", "Landschap 100", "Analoge film",
     lambda c: schouder(kleur_sat(kleur_sat(contrast(saturatie(c, 1.3), 1.15), 0.33, 1.15), 0.6, 1.2)),
     (15, 5, 5, 20, 0)),
    ("goud", "Goud 200", "Analoge film",
     lambda c: schouder(split(wit(lift_gain(saturatie(c, 1.08), 0.03), 0.09, 0.0), (0.52, 0.50, 0.42), (0.62, 0.55, 0.40), 0.7), 0.72),
     (30, 15, 10, 25, 0)),
    ("groen", "Groen 400", "Analoge film",
     lambda c: schouder(split(lift_gain(saturatie(c, 0.92), 0.035), (0.42, 0.58, 0.48), (0.55, 0.53, 0.48), 0.8), 0.72),
     (30, 10, 5, 25, 0)),
    ("dia", "Dia 50", "Analoge film",
     lambda c: kleur_sat(contrast(saturatie(c, 1.5), 1.3), 0.6, 1.15),
     (10, 5, 5, 30, 0)),
    ("kunstlicht", "Kunstlicht 800", "Analoge film",
     lambda c: schouder(split(wit(contrast(c, 1.08), -0.12, 0.03), (0.42, 0.48, 0.62), (0.62, 0.50, 0.45), 0.6)),
     (35, 70, 30, 30, 0)),
    ("super8", "Super 8", "Retro",
     lambda c: schouder(wit(lift_gain(contrast(saturatie(c, 0.78), 0.9), 0.06, 0.95), 0.12, 0.0), 0.65),
     (65, 20, 15, 55, 35)),
    ("vhs", "VHS '93", "Retro",
     lambda c: split(lift_gain(contrast(saturatie(c, 0.72), 0.85), 0.05, 0.94), (0.50, 0.42, 0.60), (0.55, 0.52, 0.50), 0.5),
     (40, 0, 20, 25, 0)),
    ("instant", "Instant", "Retro",
     lambda c: schouder(split(lift_gain(contrast(saturatie(c, 0.85), 0.8), 0.09, 0.97), (0.40, 0.58, 0.60), (0.60, 0.56, 0.46), 0.8), 0.68),
     (30, 0, 15, 40, 10)),
    ("seventies", "Seventies", "Retro",
     lambda c: schouder(kleur_sat(wit(contrast(saturatie(c, 1.25), 1.1), 0.08, 0.02), 0.0, 1.25)),
     (40, 15, 10, 40, 20)),
    ("korrel", "Korrel 400", "Zwart-wit",
     lambda c: contrast(zwartwit(c, (0.36, 0.55, 0.09)), 1.45),
     (60, 0, 10, 40, 0)),
    ("fijn", "Fijn 100", "Zwart-wit",
     lambda c: schouder(contrast(zwartwit(c), 1.1)),
     (15, 0, 5, 25, 0)),
    ("noir", "Noir", "Zwart-wit",
     lambda c: contrast(lift_gain(zwartwit(c, (0.40, 0.50, 0.10)), -0.03, 1.0, 0.9), 1.8),
     (35, 0, 15, 70, 0)),
    ("zilver", "Zilver", "Zwart-wit",
     lambda c: lift_gain(contrast(zwartwit(c), 0.78), 0.08, 0.96),
     (25, 0, 10, 20, 0)),
    ("gouden", "Gouden uur", "Warm",
     lambda c: schouder(split(wit(saturatie(c, 1.15), 0.12, 0.02), (0.52, 0.48, 0.44), (0.66, 0.54, 0.38), 0.7), 0.72),
     (10, 25, 35, 25, 25)),
    ("zomer", "Zomer pop", "Warm",
     lambda c: schouder(kleur_sat(lift_gain(saturatie(c, 1.35), 0.0, 1.04, 1.06), 0.5, 1.15), 0.8),
     (5, 10, 25, 15, 15)),
    ("tropisch", "Tropisch", "Warm",
     lambda c: schouder(huid_naar(kleur_sat(saturatie(c, 1.2), 0.48, 1.35, 0.1), (1, .62, .44), .25)),
     (5, 10, 20, 15, 0)),
    ("noords", "Noords", "Koel",
     lambda c: schouder(split(wit(saturatie(c, 0.72), -0.08, 0.0), (0.44, 0.52, 0.58), (0.50, 0.53, 0.56), 0.6), 0.75),
     (15, 0, 10, 30, 0)),
    ("bos", "Donker bos", "Koel",
     lambda c: schouder(kleur_sat(split(lift_gain(contrast(saturatie(c, 0.82), 1.2), 0.0, 0.9, 0.92), (0.42, 0.55, 0.48), (0.52, 0.54, 0.50), 0.7), 0.33, 0.9)),
     (25, 5, 10, 55, 0)),
    ("arctisch", "Arctisch", "Koel",
     lambda c: schouder(split(lift_gain(saturatie(c, 0.82), 0.02, 1.06, 1.08), (0.44, 0.55, 0.62), (0.52, 0.55, 0.58), 0.6), 0.78),
     (10, 0, 25, 15, 0)),
]


def rooster():
    a = np.linspace(0, 1, N)
    b, g, r = np.meshgrid(a, a, a, indexing="ij")  # .cube: rood loopt het snelst
    return np.stack([r, g, b], -1).reshape(-1, 3)


def schrijf_cube(pad: Path, titel: str, waarden: np.ndarray) -> None:
    regels = [f'TITLE "{titel}"', f"LUT_3D_SIZE {N}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    regels += [f"{r:.4f} {g:.4f} {b:.4f}" for r, g, b in np.clip(waarden, 0, 1)]
    pad.write_text("\n".join(regels) + "\n", encoding="ascii")


def main() -> None:
    uit = Path(sys.argv[1] if len(sys.argv) > 1 else "looks")
    uit.mkdir(parents=True, exist_ok=True)
    rg = rooster()
    index = []
    for lid, naam, sfeer, f, fx in LOOKS:
        w = np.clip(f(rg.copy()), 0, 1)
        schrijf_cube(uit / f"{lid}.cube", naam, w)
        index.append({"id": lid, "naam": naam, "sfeer": sfeer, "lut": f"{lid}.cube",
                      "afwerking": dict(zip(["korrel", "halation", "gloed", "vignet", "lichtlek"], fx))})
    (uit / "looks.json").write_text(json.dumps({"versie": 1, "grootte": N, "looks": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(index)} looks naar {uit}")


if __name__ == "__main__":
    main()
