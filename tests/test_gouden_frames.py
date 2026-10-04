"""De gouden-frames-poort uit PLAN-v2 §4.4: voorvertoning = export.

Zes vaste beelden × zes looks, allebei door de native compositor: één keer als
voorbeeld-PNG zoals stap Look hem toont, één keer uit de echte render. De eis:
ΔE2000 gemiddeld ≤ 1 en maximaal ≤ 3.

Dit is een ándere poort dan `test_compositor.py`. Die vergelijkt de GPU met de
numpy-tweeling, per pixel, en bewijst dat de shaders rekenen wat de wiskunde
zegt. Deze poort bewijst dat de twee *wegen door de engine* op hetzelfde
uitkomen: zelfde LUT, zelfde sterkte, zelfde afwerking, zelfde framenummer,
zelfde seed. Daar zit de fout die een gebruiker merkt — een voorbeeld dat niet
is wat hij krijgt.

**Waarom hij op tegels van 16×16 meet en niet per pixel.** Dat is op
03-10-2026 uitgemeten, stap voor stap:

| wat                                   | ΔE2000 gem | max  |
|---|---|---|
| invoer van de compositor, beide wegen |       0,08 |  4,2 |
| JPG op `-q:v 2` (daarom nu PNG)       |       0,74 |  9,9 |
| één h264-generatie van de export      |  1,25–2,40 | 65,6 |
| de staart (muziek, titels) — kopieert |       0,00 |  0,0 |

De export is H.264 op 4:2:0. Filmkorrel is hoogfrequente ruis en precies wat
een videocodec weggooit; op een verzadigde rand gooit 4:2:0 er bovenop nog
chroma weg. Per pixel kan een PNG daarom nooit binnen ΔE 3 van een mp4 liggen,
hoe goed de kleurweg ook is — dat is de codec, niet de look. Wat wél moet
kloppen is de kléur, en die meet je door per tegel te gemiddelden: codecruis en
korrel zijn nulgemiddeld en verdwijnen, een verkeerde LUT of sterkte niet.
16×16 geeft 30×22 kleurvlakken per beeld. Op die maat haalt de keten de eis van
§4.4 met ruimte (gemeten: gemiddeld 0,29–0,68, maximaal 2,14).

Dat het geen tandeloze maat is, bewijst `test_een_verkeerd_framenummer_valt_op`
hieronder: één framenummer ernaast en de poort slaat alsnog aan.

Zonder compositor-binary slaat hij zichzelf over: dan rendert de look via de
ffmpeg-filters en meet deze vergelijking iets anders dan waar hij over gaat.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from cve import compositor, looks, paths, render as render_mod
from cve.edl import EDL, Afwerking, Canvas, Look, Overgang, VideoBlok

from test_rpc_project import _vraag, nodig_ffmpeg


def _software_adapter() -> bool:
    info = compositor.info() if compositor.binary() is not None else None
    # Software (WARP/lavapipe) of een paravirtuele GPU in een VM-runner:
    # daar draait ook VideoToolbox/MF in software, en dat meet de encoder van
    # de runner, niet de kleurweg (Intel-runner 03-10: ΔE gem 1,09).
    return bool(info) and (
        info.get("backend") == "software" or "paravirtual" in str(info.get("adapter", "")).lower()
    )


# PLAN-v2 §4.4: de poort draait op een echte GPU. Op een runner zonder GPU
# (WARP/lavapipe) meet hij ook de software-decoder en de noodencoder van die
# machine, en dat is geen bewijs over de kleurweg. Gemeten 03-10-2026 op de
# Windows-runner: ΔE gemiddeld 1,1–1,7 — open punt voor de Windows-VM-test.
geen_echte_gpu = pytest.mark.skipif(
    _software_adapter(), reason="geen echte GPU: telt niet als bewijs (PLAN-v2 §4.4)"
)

sys.path.insert(0, str(Path(__file__).parent))
import ref_compositor as ref  # noqa: E402

# Zes beelden, geen zes willekeurige: elk een ander patroon, zodat een fout in
# één hoek van het kleurbereik (donker, verzadigd, vlak) opvalt.
PATRONEN = [
    "testsrc2=size=480x360:rate=30:duration=2",
    "gradients=size=480x360:rate=30:duration=2:c0=black:c1=white",
    "color=c=0x101418:size=480x360:rate=30:duration=2",
    "smptebars=size=480x360:rate=30:duration=2",
    "color=c=0xF2EDE4:size=480x360:rate=30:duration=2",
    "testsrc=size=480x360:rate=30:duration=2",
]
# Zes looks, gelijkmatig over de catalogus van 24 en dus over alle zes sferen.
LOOKS = ["blockbuster", "portret", "dia", "instant", "noir", "tropisch"]
STERKTE = 0.85
# Alles aan wat van het framenummer afhangt (korrel, filmtrilling) plus de
# effecten die het verst uit elkaar liepen (vignet, halation, gloed).
AFWERKING = {"korrel": 0.25, "halation": 0.20, "gloed": 0.20, "vignet": 0.30,
             "filmtrilling": 0.15, "kleurrand": 0.20}
BLOK_FRAMES = 12
CANVAS = Canvas(breedte=480, hoogte=360, fps=30)


def _clipnaam(i: int) -> str:
    return f"C{i + 1:02d}"


@pytest.fixture(scope="module")
def goudenproject(tmp_path_factory):
    """Zes clips, zes proxies, één EDL van zes blokken op een rij."""
    if not paths.heeft_ffmpeg():
        pytest.skip("ffmpeg/ffprobe niet gevonden")
    basis = tmp_path_factory.mktemp("gouden")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "PROJECTEN", basis / "projecten")
        _vraag("project.maak", naam="gouden")
        pdir = paths.project_dir("gouden")
        for i, patroon in enumerate(PATRONEN):
            naam = _clipnaam(i)
            for doel in (pdir / "bronnen" / f"{naam}.mp4", pdir / "proxies" / f"{naam}.mp4"):
                subprocess.run(
                    [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", patroon,
                     "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", str(doel)],
                    check=True, capture_output=True, timeout=300,
                )
        yield "gouden", pdir


def _edl(look: Look, afw: Afwerking) -> EDL:
    edl = EDL(project="gouden", canvas=CANVAS)
    edl.look, edl.afwerking = look, afw
    edl.video = [
        VideoBlok(
            id=f"B{i + 1:02d}", clip=_clipnaam(i), bestand=f"{_clipnaam(i)}.mp4",
            # 0,5 s in de clip: na de aanloop, en ver van een scènewissel.
            bron_start=0.5, duur=BLOK_FRAMES / CANVAS.fps,
            tijdlijn_start=i * BLOK_FRAMES / CANVAS.fps,
            frames=BLOK_FRAMES, vulmodus="vul", zoom="geen",
            overgang_in=Overgang(soort="snede", duur=0.0),
        )
        for i in range(len(PATRONEN))
    ]
    return edl


def _frames_uit(pad: Path, indexen: list[int]) -> list[np.ndarray]:
    """De gevraagde framenummers uit een video, als RGB in 0..1."""
    keuze = "+".join(f"eq(n\\,{n})" for n in indexen)
    r = subprocess.run(
        [str(paths.ffmpeg()), "-hide_banner", "-loglevel", "error", "-i", str(pad),
         "-vf", f"select='{keuze}'", "-vsync", "0", "-frames:v", str(len(indexen)),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=300,
    )
    stap = CANVAS.breedte * CANVAS.hoogte * 3
    assert len(r.stdout) == stap * len(indexen), (len(r.stdout), stap * len(indexen))
    ruw = np.frombuffer(r.stdout, np.uint8).reshape(len(indexen), CANVAS.hoogte,
                                                    CANVAS.breedte, 3)
    return [ruw[i].astype(np.float32) / 255.0 for i in range(len(indexen))]


TEGEL = 16


def _tegels(a: np.ndarray, k: int = TEGEL) -> np.ndarray:
    """Het beeld als tegels van k×k, elk het gemiddelde van zijn pixels."""
    h, b = a.shape[0] // k * k, a.shape[1] // k * k
    return a[:h, :b].reshape(h // k, k, b // k, k, 3).mean(axis=(1, 3))


def _png(pad: Path) -> np.ndarray:
    r = subprocess.run(
        [str(paths.ffmpeg()), "-hide_banner", "-loglevel", "error", "-i", str(pad),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=120,
    )
    return (np.frombuffer(r.stdout, np.uint8)
            .reshape(CANVAS.hoogte, CANVAS.breedte, 3).astype(np.float32) / 255.0)


@nodig_ffmpeg
@geen_echte_gpu
@pytest.mark.skipif(compositor.binary() is None,
                    reason="compositor niet gebouwd (cargo build --release)")
@pytest.mark.parametrize("look_id", LOOKS)
def test_voorbeeld_is_kleurgetrouw_aan_de_render(goudenproject, look_id, capsys):
    """Per look: zes beelden uit het voorbeeld naast zes uit de render."""
    project, pdir = goudenproject
    look, afw = Look(id=look_id, sterkte=STERKTE), Afwerking(**AFWERKING)
    _edl(look, afw).schrijf(pdir / "edl.json")

    gerenderd = render_mod.render(
        project, opties=render_mod.RenderOpties(modus="preview"), log=lambda *_: None
    )
    # Het eerste frame van elk blok. Daar kent `looks.voorbeeld()` het
    # framenummer van, en dus de stand van korrel en filmtrilling.
    indexen = [i * BLOK_FRAMES for i in range(len(PATRONEN))]
    uit_render = _frames_uit(gerenderd, indexen)

    gemiddelden, maxima, per_pixel = [], [], []
    for i, na_render in enumerate(uit_render):
        uit = looks.voorbeeld(project, look_id, STERKTE, AFWERKING,
                              clip=_clipnaam(i), breedte=0)
        voorbeeld = _png(Path(uit["pad"]))
        de = ref.delta_e2000(_tegels(na_render), _tegels(voorbeeld))
        gemiddelden.append(float(de.mean()))
        maxima.append(float(de.max()))
        per_pixel.append(float(ref.delta_e2000(na_render, voorbeeld).mean()))

    # Het getal per pixel staat erbij als naslag: dat is de codec, niet de
    # kleurweg. Loopt het ver op zonder dat de tegels bewegen, dan is er iets
    # met de korrel of met de encoder gebeurd.
    with capsys.disabled():
        print(f"\n{look_id}: tegels van {TEGEL}px ΔE2000 gemiddeld "
              f"{max(gemiddelden):.2f}, maximaal {max(maxima):.2f}  "
              f"(per pixel gemiddeld {max(per_pixel):.2f})")
    assert max(gemiddelden) <= 1.0, f"{look_id}: ΔE2000 gemiddeld {max(gemiddelden):.3f}"
    assert max(maxima) <= 3.0, f"{look_id}: ΔE2000 maximaal {max(maxima):.3f}"


@nodig_ffmpeg
@geen_echte_gpu
@pytest.mark.skipif(compositor.binary() is None, reason="compositor niet gebouwd")
def test_een_verkeerd_framenummer_valt_op(goudenproject, capsys):
    """Bewijst dat de poort tanden heeft.

    Korrel en filmtrilling rekenen met het framenummer. Stond dat in het
    voorbeeld op 0 terwijl de render bij shot 4 op frame 36 zit — precies de
    fout die hier tot 03-10-2026 in zat — dan moet de poort aanslaan. Zonder
    deze test zou niemand weten of 16×16-tegels dat nog zien.
    """
    project, pdir = goudenproject
    look, afw = Look(id="blockbuster", sterkte=STERKTE), Afwerking(**AFWERKING)
    _edl(look, afw).schrijf(pdir / "edl.json")
    gerenderd = render_mod.render(
        project, opties=render_mod.RenderOpties(modus="preview"), log=lambda *_: None
    )
    blok = 3
    index = blok * BLOK_FRAMES
    na_render = _tegels(_frames_uit(gerenderd, [index])[0])

    def de_bij(vanaf: int) -> float:
        rgba = _compositorframe(pdir, _clipnaam(blok), look, afw, vanaf)
        return float(ref.delta_e2000(na_render, _tegels(rgba)).max())

    goed, fout = de_bij(index), de_bij(0)
    with capsys.disabled():
        print(f"\nframenummer {index}: ΔE2000 max {goed:.2f}   "
              f"framenummer 0 (de oude fout): {fout:.2f}")
    assert goed <= 3.0, f"het juiste framenummer hoort te passen: {goed:.3f}"
    assert fout > 3.0, f"een verkeerd framenummer glipt erdoor: {fout:.3f}"


def _compositorframe(pdir: Path, clip: str, look: Look, afw: Afwerking,
                     vanaf: int) -> np.ndarray:
    """Hetzelfde als `looks.voorbeeld()`, maar met het framenummer in de hand.

    Alleen voor de test hierboven: `voorbeeld()` leidt het framenummer zelf af
    uit de EDL, en dat is precies wat we hier willen kunnen vervalsen.
    """
    from cve.render import voorbeeldfilter

    filters = voorbeeldfilter(look, afw, CANVAS, aanloop=0.5, breedte=0,
                              seed=0, uitvoer="rgba")
    d = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-i", str(pdir / "proxies" / f"{clip}.mp4"),
         "-frames:v", "1", "-map", "0:v:0", "-an", "-vf", filters,
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True, timeout=300,
    )
    uit = compositor.frames(d.stdout, CANVAS.breedte, CANVAS.hoogte, look, afw,
                            seed=0, vanaf=vanaf)
    return (np.frombuffer(uit, np.uint8)
            .reshape(CANVAS.hoogte, CANVAS.breedte, 4)[:, :, :3]
            .astype(np.float32) / 255.0)
