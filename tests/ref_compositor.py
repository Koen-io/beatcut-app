"""Numpy-tweeling van `app/shaders/*.wgsl` — exact dezelfde wiskunde.

Dit bestand bestaat om één reden: de shaders op de GPU controleren zonder de
GPU te hoeven geloven. Elke functie hier is een letterlijke vertaling van een
entry point in `look.wgsl` of `afwerking.wgsl`. Wijkt de compositor hiervan af,
dan is er iets mis met de pijplijn, de bindings of de shader — en dat is
precies wat `tests/test_compositor.py` meet (ΔE2000 gem ≤ 1, max ≤ 3).

Wijzig je een shader, dan wijzig je hier mee. Eén van de twee alleen aanpassen
maakt de poort stil onbruikbaar in plaats van rood.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HOOGLICHT_GLOED = 185.0 / 255.0
HOOGLICHT_HALATION = 205.0 / 255.0
# Zachte band rond de drempel — zie de uitleg bij `hooglichten` in afwerking.wgsl.
HOOGLICHT_BAND = 4.0 / 255.0


# -- LUT -------------------------------------------------------------------


def lees_cube(pad: Path | None) -> tuple[np.ndarray, int]:
    """`.cube` als tabel [n*n*n, 3] met rood als snelste as."""
    if pad is None:
        rooster = np.indices((2, 2, 2)).reshape(3, -1).T.astype(np.float32)  # b,g,r
        return rooster[:, ::-1].copy(), 2
    maat = 0
    rijen: list[list[float]] = []
    for regel in Path(pad).read_text(encoding="utf-8").splitlines():
        regel = regel.strip()
        if not regel or regel.startswith("#"):
            continue
        if regel.startswith("LUT_3D_SIZE"):
            maat = int(regel.split()[1])
            continue
        if regel[0] not in "0123456789-.":
            continue
        getallen = [float(x) for x in regel.split()]
        if len(getallen) == 3:
            rijen.append(getallen)
    return np.asarray(rijen, dtype=np.float32), maat


def lut_tetra(kleur: np.ndarray, tabel: np.ndarray, n: int) -> np.ndarray:
    """Tetraëdrische interpolatie, gelijk aan ffmpeg `lut3d=interp=tetrahedral`."""
    maxi = n - 1
    s = np.clip(kleur, 0.0, 1.0) * maxi
    i = np.minimum(np.floor(s).astype(np.int64), maxi - 1)
    d = s - i

    def op(dr: int, dg: int, db: int) -> np.ndarray:
        idx = ((i[..., 2] + db) * n + (i[..., 1] + dg)) * n + (i[..., 0] + dr)
        return tabel[idx]

    dr, dg, db = d[..., 0:1], d[..., 1:2], d[..., 2:3]
    c000, c111 = op(0, 0, 0), op(1, 1, 1)
    uit = np.zeros_like(kleur)

    # Zes tetraëders; dezelfde takken en dezelfde volgorde als in look.wgsl.
    takken = [
        ((dr > dg) & (dg > db), (1 - dr) * c000 + (dr - dg) * op(1, 0, 0) + (dg - db) * op(1, 1, 0) + db * c111),
        ((dr > dg) & ~(dg > db) & (dr > db), (1 - dr) * c000 + (dr - db) * op(1, 0, 0) + (db - dg) * op(1, 0, 1) + dg * c111),
        ((dr > dg) & ~(dg > db) & ~(dr > db), (1 - db) * c000 + (db - dr) * op(0, 0, 1) + (dr - dg) * op(1, 0, 1) + dg * c111),
        (~(dr > dg) & (db > dg), (1 - db) * c000 + (db - dg) * op(0, 0, 1) + (dg - dr) * op(0, 1, 1) + dr * c111),
        (~(dr > dg) & ~(db > dg) & (db > dr), (1 - dg) * c000 + (dg - db) * op(0, 1, 0) + (db - dr) * op(0, 1, 1) + dr * c111),
        (~(dr > dg) & ~(db > dg) & ~(db > dr), (1 - dg) * c000 + (dg - dr) * op(0, 1, 0) + (dr - db) * op(1, 1, 0) + db * c111),
    ]
    for masker, waarde in takken:
        uit = np.where(np.broadcast_to(masker, uit.shape), waarde, uit)
    return uit


# -- afwerking -------------------------------------------------------------


def kernel(sigma: float) -> np.ndarray:
    """Zelfde gewichten als `compositor::kernel`."""
    straal = int(min(max(np.ceil(3.0 * sigma), 1), 64))
    k = np.arange(-straal, straal + 1, dtype=np.float32)
    w = np.exp(-(k * k) / (2.0 * sigma * sigma)).astype(np.float32)
    return w / w.sum()


def _vervaag_as(beeld: np.ndarray, w: np.ndarray, as_: int) -> np.ndarray:
    """Convolutie met vastgeklemde randen, zoals `klem_xy` in de shader."""
    straal = (len(w) - 1) // 2
    uit = np.zeros_like(beeld)
    n = beeld.shape[as_]
    for j, gewicht in enumerate(w):
        verschuiving = j - straal
        idx = np.clip(np.arange(n) + verschuiving, 0, n - 1)
        uit += gewicht * np.take(beeld, idx, axis=as_)
    return uit


def _screen(onder: np.ndarray, boven: np.ndarray, dekking: float) -> np.ndarray:
    s = 1.0 - (1.0 - onder) * (1.0 - boven)
    return onder + (s - onder) * dekking


def _hash32(x: np.ndarray) -> np.ndarray:
    v = x.astype(np.uint32)
    with np.errstate(over="ignore"):
        v = v ^ (v >> np.uint32(16))
        v = v * np.uint32(2654435769)
        v = v ^ (v >> np.uint32(15))
        v = v * np.uint32(2246822519)
        v = v ^ (v >> np.uint32(16))
    return v


def _ruis(h: int, b: int, frame: int, seed: int) -> np.ndarray:
    y, x = np.meshgrid(np.arange(h, dtype=np.uint32), np.arange(b, dtype=np.uint32), indexing="ij")
    with np.errstate(over="ignore"):
        sleutel = (
            x * np.uint32(374761393)
            + y * np.uint32(668265263)
            + np.uint32(frame) * np.uint32(2147483647)
            + np.uint32(seed) * np.uint32(362437)
        )
    return (_hash32(sleutel).astype(np.float64) / 4294967295.0 * 2.0 - 1.0).astype(np.float32)


def _bilineair(beeld: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    h, b = beeld.shape[:2]
    x0, y0 = np.floor(u), np.floor(v)
    fx, fy = (u - x0)[..., None], (v - y0)[..., None]
    xi, yi = x0.astype(np.int64), y0.astype(np.int64)

    def haal(dx: int, dy: int) -> np.ndarray:
        return beeld[np.clip(yi + dy, 0, h - 1), np.clip(xi + dx, 0, b - 1)]

    boven = haal(0, 0) + (haal(1, 0) - haal(0, 0)) * fx
    onder = haal(0, 1) + (haal(1, 1) - haal(0, 1)) * fx
    return boven + (onder - boven) * fy


def verwerk(
    rgb: np.ndarray, *, lut: Path | None, sterkte: float, afwerking: dict, seed: int = 0, frame: int = 0
) -> np.ndarray:
    """Eén frame door de hele keten. In en uit: float32 [h, w, 3] in 0..1."""
    h, b = rgb.shape[:2]
    afw = {k: float(afwerking.get(k, 0.0)) for k in
           ("korrel", "halation", "gloed", "vignet", "lichtlek", "breedbeeld", "filmtrilling", "kleurrand")}

    tabel, n = lees_cube(lut)
    beeld = rgb + (lut_tetra(rgb, tabel, n) - rgb) * float(np.clip(sterkte, 0.0, 1.0))

    for sterk, drempel, factor, fractie, minsigma, kleur in (
        (afw["gloed"], HOOGLICHT_GLOED, 0.75, 0.012, 1.0, (1.0, 1.0, 1.0)),
        (afw["halation"], HOOGLICHT_HALATION, 0.85, 0.024, 2.0, (1.0, 0.30, 0.10)),
    ):
        if sterk <= 0:
            continue
        w = kernel(max(fractie * h, minsigma))
        t = np.clip((beeld - drempel) / HOOGLICHT_BAND, 0.0, 1.0)
        tak = (beeld * (t * t * (3.0 - 2.0 * t))).astype(np.float32)
        tak = _vervaag_as(_vervaag_as(tak, w, 1), w, 0) * np.asarray(kleur, dtype=np.float32)
        beeld = _screen(beeld, tak, factor * sterk)

    if afw["lichtlek"] > 0 or afw["korrel"] > 0 or afw["vignet"] > 0:
        if afw["lichtlek"] > 0:
            u = (np.arange(b, dtype=np.float32) / b)[None, :]
            v = (np.arange(h, dtype=np.float32) / h)[:, None]
            afstand = np.clip(1.0 - np.sqrt(u * u + v * v) / 1.41421356, 0.0, 1.0)
            lek = (afstand**2)[..., None] * np.asarray([1.0, 0.58, 0.22], dtype=np.float32)
            beeld = _screen(beeld, lek, 0.55 * afw["lichtlek"])
        if afw["korrel"] > 0:
            kracht = max(1.0, round(2.0 + 22.0 * afw["korrel"])) / 255.0
            beeld = beeld + _ruis(h, b, frame, seed)[..., None] * kracht
        if afw["vignet"] > 0:
            hoek = 0.20 + 1.00 * afw["vignet"]
            dx = (np.arange(b, dtype=np.float32) + 0.5) / b - 0.5
            dy = (np.arange(h, dtype=np.float32) + 0.5) / h - 0.5
            r = np.sqrt(dx[None, :] ** 2 + dy[:, None] ** 2) / 0.70710678
            beeld = beeld * (np.maximum(np.cos(hoek * r), 0.0) ** 4)[..., None]
        beeld = np.clip(beeld, 0.0, 1.0)

    if afw["kleurrand"] > 0 or afw["filmtrilling"] > 0 or afw["breedbeeld"] > 0:
        u = np.tile(np.arange(b, dtype=np.float32), (h, 1))
        v = np.tile(np.arange(h, dtype=np.float32)[:, None], (1, b))
        if afw["filmtrilling"] > 0:
            amp = max(1.0, round(0.003 * h * afw["filmtrilling"]))
            fx = 1.9 + (seed % 7) * 0.11
            fy = 1.31 + (seed % 5) * 0.09
            u = (u + amp + amp * np.sin(frame * fx)) * (b / (b + 2.0 * amp))
            v = (v + amp + amp * np.sin(frame * fy)) * (h / (h + 2.0 * amp))
        if afw["kleurrand"] > 0:
            px = max(1.0, round(0.0015 * b * afw["kleurrand"]))
            beeld = np.stack([
                _bilineair(beeld, u - px, v)[..., 0],
                _bilineair(beeld, u, v)[..., 1],
                _bilineair(beeld, u + px, v)[..., 2],
            ], axis=-1)
        else:
            beeld = _bilineair(beeld, u, v)
        if afw["breedbeeld"] > 0:
            doelh = (int(b / 2.39) // 2) * 2
            if 0 < doelh < h:
                boven = (h - doelh) // 2
                masker = np.zeros((h, 1, 1), dtype=np.float32)
                masker[boven:boven + doelh] = 1.0
                beeld = beeld * masker
        beeld = np.clip(beeld, 0.0, 1.0)

    return np.clip(beeld, 0.0, 1.0).astype(np.float32)


# -- overgangen ------------------------------------------------------------
#
# De tweeling van `app/shaders/overgangen.wgsl`, met het kader op de eenheid:
# precies wat `compositor/src/overgang.rs` de shader voert. In de export heeft
# ffmpeg de blokken al op canvasformaat gezet, dus `u.bronA`/`u.bronB` staan op
# schaal 1 / verschuiving 0 en de vulmodus is "vul". `o_naar_bron()`,
# `o_naar_pas()` en `o_naar_canvas()` zijn dan de identiteit, en `o_samenstel()`
# is één monster.
#
# De voorvertoning voert dezelfde shader andere kaders (vulmodus plus Ken
# Burns). Dat deel meet deze tweeling niet — dat is wat
# `tests/test_overgangen_export.py` en de speler-QA doen.

O_NAMEN = (
    "snede", "crossfade", "dip_zwart", "dip_wit", "glitch", "pixel", "slice",
    "whip_pan", "zoom_punch", "wipe", "radiaal", "film_brand", "lichtlek",
    "rgb_split",
)

O_GAMMA = 2.2


def _o_ruis(a, b, c) -> np.ndarray:
    """`o_ruis()`: tussen 0 en 1 uit drie gehele getallen, via dezelfde hash.

    `a` en `b` zijn i32 (band-, strook- of blokindex), `c` is u32. Alles
    rekent u32-wrappend, net als WGSL.

    Nooit precies 0 en nooit precies 1: 23 bits van de hash, een halve stap
    opgeschoven, gedeeld door 2^23. Zie de uitleg bij `o_ruis()` in
    `app/shaders/overgangen.wgsl` — een drempel van 0 betekent "al omgeklapt
    voor de overgang begint". Beide kanten rekenen dit exact in een f32, dus
    deze tweeling en de GPU komen hier op dezelfde bits uit.
    """
    au = (np.asarray(a).astype(np.int64) & 0xFFFFFFFF).astype(np.uint32)
    bu = (np.asarray(b).astype(np.int64) & 0xFFFFFFFF).astype(np.uint32)
    with np.errstate(over="ignore"):
        sleutel = (au * np.uint32(374761393)
                   + bu * np.uint32(668265263)
                   + np.uint32(int(c) & 0xFFFFFFFF) * np.uint32(2147483647))
    return ((_hash32(sleutel) >> np.uint32(9)).astype(np.float64) + 0.5) / 8388608.0


def _o_monster(beeld: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """`o_monster()`: uv geklemd op 0..1, lineair gefilterd, randen geklemd."""
    h, b = beeld.shape[:2]
    return _bilineair(beeld, np.clip(u, 0.0, 1.0) * b - 0.5,
                      np.clip(v, 0.0, 1.0) * h - 0.5)


def _o_binnen(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    binnen = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
    return binnen.astype(np.float64)[..., None]


def _o_tap(beeld: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """`o_tap()` met de eenheid als kader: buiten het canvas zwart."""
    return _o_monster(beeld, u, v) * _o_binnen(u, v)


def _o_kies(keuze: np.ndarray, uit_a: np.ndarray, uit_b: np.ndarray) -> np.ndarray:
    """`o_tap(keuze, ...)` waarbij `keuze` per pixel 0 of 1 is."""
    return np.where(keuze[..., None] > 0.5, uit_b, uit_a)


def _o_lin(c: np.ndarray) -> np.ndarray:
    return np.power(np.maximum(c, 0.0), O_GAMMA)


def _o_srgb(c: np.ndarray) -> np.ndarray:
    return np.power(np.maximum(c, 0.0), 1.0 / O_GAMMA)


def _o_meng_licht(a: np.ndarray, b: np.ndarray, f) -> np.ndarray:
    la, lb = _o_lin(a), _o_lin(b)
    return _o_srgb(la + (lb - la) * f)


def _smoothstep(e0: float, e1: float, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _o_raster(grof: float, verh: float) -> tuple[float, float]:
    """Het mozaïekraster van `pixel`, in cellen breed en hoog.

    De tweeling van `o_pixelraster()` in de shader; die krijgt `puls` mee en
    rekent `grof` zelf uit.
    """
    return (max(2.0, float(np.round(grof * verh))), max(2.0, float(np.round(grof))))


def overgang(a_beeld: np.ndarray, b_beeld: np.ndarray, soort, t: float, *,
             frame: int = 0, seed: int = 0) -> np.ndarray:
    """`overgang_canvas_uv()` + `overgang_meng()` op twee frames van gelijke maat.

    In en uit: float [h, w, 3] in 0..1. `soort` is een naam uit `O_NAMEN` of
    de index daarin (dezelfde volgorde als `edl.OVERGANGEN`). `t` loopt 0..1,
    `frame` is de doorlopende frame-index van de tijdlijn en `seed` de
    effectseed uit `edl.json`.
    """
    nr = O_NAMEN.index(soort) if isinstance(soort, str) else int(soort)
    h, b = a_beeld.shape[:2]
    a_beeld = a_beeld.astype(np.float64)
    b_beeld = b_beeld.astype(np.float64)
    yy, xx = np.mgrid[0:h, 0:b].astype(np.float64)
    u, v = (xx + 0.5) / b, (yy + 0.5) / h
    verh = max(0.01, b / h)
    tt = float(np.clip(t, 0.0, 1.0))
    puls = float(np.sin(tt * np.pi))
    vast = int(seed)
    fr = max(0, int(frame))

    # `overgang_canvas_uv()`: alleen `pixel` vervormt de uv's, en dat doet hij
    # in canvas-uv. Hier is dat hetzelfde als bron-uv (het kader is de
    # eenheid). Daarna samplet de fragment-shader A en B op die uv en klemt ze
    # op 0..1.
    if nr == O_NAMEN.index("pixel"):
        rb, rh = _o_raster(4096.0 + (11.0 - 4096.0) * np.sin(tt * np.pi), verh)
        ua = (np.floor(u * rb) + 0.5) / rb
        va = (np.floor(v * rh) + 0.5) / rh
        ub, vb = ua, va
    else:
        ua, va, ub, vb = u, v, u, v
    a = _o_monster(a_beeld, np.clip(ua, 0.0, 1.0), np.clip(va, 0.0, 1.0))
    bb = _o_monster(b_beeld, np.clip(ub, 0.0, 1.0), np.clip(vb, 0.0, 1.0))

    uit = _o_meng(nr, a, bb, a_beeld, b_beeld, u, v, tt, puls, verh, fr, vast)
    return np.clip(uit, 0.0, 1.0).astype(np.float32)


def _o_meng(nr, a, b, a_beeld, b_beeld, u, v, tt, puls, verh, fr, vast):
    """`o_meng()`, overgang voor overgang. Zonder de klem: die zit in
    `overgang_meng()` en dus in `overgang()` hierboven."""
    naam = O_NAMEN[nr]

    if naam == "snede":
        return b if tt >= 1.0 else a

    if naam == "crossfade":
        return _o_meng_licht(a, b, tt)

    if naam == "dip_zwart":
        dicht = abs(tt - 0.5) * 2.0
        c = b if tt >= 0.5 else a
        return c * (dicht ** (1.0 / O_GAMMA))

    if naam == "dip_wit":
        dicht = abs(tt - 0.5) * 2.0
        c = _o_lin(b if tt >= 0.5 else a)
        return _o_srgb(1.0 + (c - 1.0) * dicht)

    if naam == "glitch":
        band = np.floor(v * 26.0).astype(np.int64)
        keuze = (_o_ruis(band, 0, vast) < _smoothstep(0.08, 0.92, tt)).astype(np.float64)
        sprong = (_o_ruis(band, 1, fr + vast) - 0.5) * 0.22 * puls
        split = 0.016 * puls
        pu, pv = u + sprong, v

        def tap(du):
            return _o_kies(keuze, _o_tap(a_beeld, pu + du, pv), _o_tap(b_beeld, pu + du, pv))

        c = np.stack([tap(split)[..., 0], tap(0.0)[..., 1], tap(-split)[..., 2]], -1)
        scheur = (_o_ruis(band, 2, fr + vast) >= 0.965).astype(np.float64) * puls
        f = (scheur * 0.75)[..., None]
        return c + (1.0 - c) * f

    if naam == "pixel":
        rb, rh = _o_raster(4096.0 + (11.0 - 4096.0) * puls, verh)
        bx = np.floor(u * rb).astype(np.int64)
        by = np.floor(v * rh).astype(np.int64)
        kies = _o_ruis(bx, by, vast) < _smoothstep(0.2, 0.8, tt)
        return np.where(kies[..., None], b, a)

    if naam == "slice":
        strook = np.floor(v * 13.0).astype(np.int64)
        kant = np.where((strook & 1) == 0, 1.0, -1.0)
        macht = 0.7 + 0.7 * _o_ruis(strook, 3, vast)
        e = np.power(_smoothstep(0.0, 1.0, tt), macht)
        pau, pav = u - e * kant, v
        pbu, pbv = u - (e - 1.0) * kant, v
        ta, tb = _o_tap(a_beeld, pau, pav), _o_tap(b_beeld, pbu, pbv)
        f = _o_binnen(pbu, pbv)
        return ta + (tb - ta) * f

    if naam == "whip_pan":
        e = _smoothstep(0.0, 1.0, tt)
        veeg = 0.22 * 6.0 * tt * (1.0 - tt)
        som = np.zeros_like(a)
        for i in range(9):
            f = (i / 8.0 - 0.5) * veeg
            som = som + _o_tap(a_beeld, u + (e + f), v)
            som = som + _o_tap(b_beeld, u + (e - 1.0 + f), v)
        return som / 9.0

    if naam == "zoom_punch":
        e = _smoothstep(0.0, 1.0, tt)
        za, zb = 1.0 + 0.45 * e, 1.0 + 0.45 * (1.0 - e)
        veeg = 0.10 * 6.0 * tt * (1.0 - tt)
        mu, mv = u - 0.5, v - 0.5
        sa, sb = np.zeros_like(a), np.zeros_like(a)
        for i in range(7):
            f = 1.0 + (i / 6.0 - 0.5) * veeg
            sa = sa + _o_tap(a_beeld, 0.5 + mu / (za * f), 0.5 + mv / (za * f))
            sb = sb + _o_tap(b_beeld, 0.5 + mu / (zb * f), 0.5 + mv / (zb * f))
        return _o_meng_licht(sa / 7.0, sb / 7.0, _smoothstep(0.35, 0.65, tt))

    if naam == "wipe":
        rand = 0.015
        grens = tt * (1.0 + 2.0 * rand) - rand
        c = _o_meng_licht(b, a, _smoothstep(grens - rand, grens + rand, u)[..., None])
        lijn = np.exp(-(((u - grens) / rand) ** 2.0))
        return c + (lijn * 0.25)[..., None]

    if naam == "radiaal":
        dx, dy = (u - 0.5) * verh, v - 0.5
        hk = np.mod(np.arctan2(dx, -dy) / (2.0 * np.pi) + 1.0, 1.0)
        rand = 0.01
        grens = tt * (1.0 + 2.0 * rand) - rand
        return _o_meng_licht(b, a, _smoothstep(grens - rand, grens + rand, hk)[..., None])

    if naam == "film_brand":
        rb, rh = float(np.round(34.0 * verh)), 34.0
        gx, gy = u * rb, v * rh
        hx, hy = np.floor(gx), np.floor(gy)
        fx, fy = gx - hx, gy - hy
        wx, wy = fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy)
        ix, iy = hx.astype(np.int64), hy.astype(np.int64)
        n00, n10 = _o_ruis(ix, iy, vast), _o_ruis(ix + 1, iy, vast)
        n01, n11 = _o_ruis(ix, iy + 1, vast), _o_ruis(ix + 1, iy + 1, vast)
        boven = n00 + (n10 - n00) * wx
        onder = n01 + (n11 - n01) * wx
        n = boven + (onder - boven) * wy
        d = np.hypot(u * verh - 0.52 * verh, v - 0.44)
        veld = d * 1.25 + (n - 0.5) * 0.30
        rand = 0.07
        grens = tt * 1.5 - 0.25
        c = _o_meng_licht(b, a, _smoothstep(grens - rand, grens + rand, veld)[..., None])
        ring = np.exp(-(((veld - grens) / rand) ** 2.0)) * puls
        heet = np.asarray([1.0, 0.52, 0.12])
        koel = np.asarray([1.0, 0.95, 0.80])
        gloed = heet + (koel - heet) * ring[..., None]
        return c + gloed * (ring * 0.85)[..., None]

    if naam == "lichtlek":
        baan = tt * 1.6 - 0.3
        d = (u - baan) * 2.2 - (v - 0.5) * 0.6
        kracht = np.exp(-d * d * 7.0) * puls
        c = _o_meng_licht(a, b, _smoothstep(0.35, 0.65, tt))
        lek = np.asarray([1.0, 0.84, 0.58]) * kracht[..., None]
        return 1.0 - (1.0 - c) * (1.0 - lek)

    if naam == "rgb_split":
        split = 0.035 * puls
        schok = float((_o_ruis(0, fr, vast) - 0.5) * 0.012 * puls)
        pu, pv = u, v + schok
        f = _smoothstep(0.3, 0.7, tt)
        ar, br_ = _o_tap(a_beeld, pu + split, pv), _o_tap(b_beeld, pu + split, pv)
        ag, bg = _o_tap(a_beeld, pu, pv), _o_tap(b_beeld, pu, pv)
        ab, bbl = _o_tap(a_beeld, pu - split, pv), _o_tap(b_beeld, pu - split, pv)
        return np.stack([
            ar[..., 0] + (br_[..., 0] - ar[..., 0]) * f,
            ag[..., 1] + (bg[..., 1] - ag[..., 1]) * f,
            ab[..., 2] + (bbl[..., 2] - ab[..., 2]) * f,
        ], -1)

    return _o_meng_licht(a, b, tt)



# -- CIEDE2000 -------------------------------------------------------------
# Zelf uitgeschreven: scikit-image zit niet in de venv en één kleurformule is
# geen reden om er een afhankelijkheid bij te zetten.


def _naar_lab(rgb: np.ndarray) -> np.ndarray:
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.asarray([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = lin @ m.T / np.asarray([0.95047, 1.00000, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e2000(rgb1: np.ndarray, rgb2: np.ndarray) -> np.ndarray:
    """ΔE2000 per pixel tussen twee RGB-beelden in 0..1."""
    lab1, lab2 = _naar_lab(rgb1.astype(np.float64)), _naar_lab(rgb2.astype(np.float64))
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cbar**7 / (cbar**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dlp = l2 - l1
    dcp = c2p - c1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, np.where(dhp < -180, dhp + 360, dhp))
    dhp = np.where(c1p * c2p == 0, 0.0, dhp)
    dHp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2)
    lbar, cbarp = (l1 + l2) / 2, (c1p + c2p) / 2
    hsom = h1p + h2p
    hbar = np.where(
        c1p * c2p == 0, hsom,
        np.where(np.abs(h1p - h2p) <= 180, hsom / 2,
                 np.where(hsom < 360, (hsom + 360) / 2, (hsom - 360) / 2)),
    )
    t = (1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar))
         + 0.32 * np.cos(np.radians(3 * hbar + 6)) - 0.20 * np.cos(np.radians(4 * hbar - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -2 * np.sqrt(cbarp**7 / (cbarp**7 + 25.0**7)) * np.sin(
        np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2)))
    )
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh))
