"""De gouden-frames-poort voor de native compositor (PLAN-v2 §4.4).

Zes vaste frames × alle 24 looks door de GPU-compositor, naast de numpy-
tweeling in `ref_compositor.py`. De eis: ΔE2000 gemiddeld ≤ 1 en maximaal ≤ 3.

Wat deze poort wél bewijst: de WGSL-shaders, de bindings en de volgorde van de
passen doen op de GPU exact wat de wiskunde zegt. Wat hij níet bewijst: dat de
engine die compositor ook op dezelfde manier aanroept vanuit stap Look en
vanuit de render — dat is `test_gouden_frames.py`.

Het verschil met de ffmpeg-keten wordt alleen gemeten en gerapporteerd
(`test_verschil_met_ffmpeg_rapporteren`): die keten is sinds 03-10-2026 de
terugval voor als het binary ontbreekt, geen tweede renderpad.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import ref_compositor as ref  # noqa: E402

WORTEL = Path(__file__).resolve().parents[1]
LOOKS = WORTEL / "looks"


def _binary() -> Path | None:
    """Via de engine en niet via een vast pad: de CI bouwt met `--target`, en
    dan staat het binary in `compositor/target/<triple>/release/`. Met een vast
    pad sloeg deze hele poort zichzelf daar stil over."""
    from cve import compositor

    return compositor.binary()


BINARY = _binary()

B, H = 96, 54  # klein: de numpy-tweeling rekent per pixel in Python

# Eén afwerking die alle zeven effecten aanzet. Alles tegelijk is strenger dan
# los testen: een fout in de volgorde van de passen valt dan pas op.
AFWERKING = {
    "korrel": 0.35, "halation": 0.40, "gloed": 0.50, "vignet": 0.30,
    "lichtlek": 0.25, "breedbeeld": 0.0, "filmtrilling": 0.40, "kleurrand": 0.50,
}
SEED = 7


def _frames() -> list[np.ndarray]:
    """Zes vaste frames: vijf gegenereerd, plus een echt beeld als dat er is.

    Vast en niet willekeurig, want een poort die elke run een ander beeld pakt
    kan niet falen op iets wat je kunt nazoeken.
    """
    y, x = np.mgrid[0:H, 0:B].astype(np.float32)
    u, v = x / (B - 1), y / (H - 1)
    uit = [
        np.stack([u, v, np.full_like(u, 0.5)], -1),                       # verloop
        np.stack([np.full_like(u, 0.02)] * 3, -1),                        # bijna zwart
        np.stack([np.full_like(u, 0.98)] * 3, -1),                        # bijna wit
        np.stack([(np.sin(u * 19) * 0.5 + 0.5), (np.cos(v * 13) * 0.5 + 0.5), u * v], -1),
        np.stack([((x.astype(int) // 8 + y.astype(int) // 8) % 2).astype(np.float32)] * 3, -1),
    ]
    echt = _echte_clip()
    uit.append(echt if echt is not None else np.stack([v, u, 1.0 - u], -1))
    return [np.clip(f, 0, 1).astype(np.float32) for f in uit]


def _echte_clip() -> np.ndarray | None:
    """Een frame uit `projecten/test/bronnen` als dat project er is."""
    from cve import paths

    bronnen = sorted((WORTEL / "projecten" / "test" / "bronnen").glob("*.*"))
    if not bronnen:
        return None
    r = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-ss", "1", "-i", str(bronnen[0]),
         "-frames:v", "1", "-vf", f"scale={B}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120,
    )
    if r.returncode != 0 or len(r.stdout) != B * H * 3:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(H, B, 3).astype(np.float32) / 255.0


def _door_compositor(frames: list[np.ndarray], lut: Path | None, sterkte: float,
                     afwerking: dict, seed: int) -> list[np.ndarray]:
    """Alle frames in één aanroep: de GPU hoeft dan maar één keer op te starten."""
    rgba = np.concatenate([
        np.dstack([np.round(f * 255).astype(np.uint8), np.full((H, B, 1), 255, np.uint8)])
        for f in frames
    ]).tobytes()
    r = subprocess.run(
        [str(BINARY), "--breedte", str(B), "--hoogte", str(H), "--aantal", str(len(frames)),
         "--lut", str(lut) if lut else "geen", "--sterkte", str(sterkte),
         "--afwerking", json.dumps(afwerking), "--seed", str(seed)],
        input=rgba, capture_output=True, timeout=300,
    )
    assert r.returncode == 0, r.stderr.decode()[-500:]
    uit = np.frombuffer(r.stdout, np.uint8).reshape(len(frames), H, B, 4)
    return [uit[i, :, :, :3].astype(np.float32) / 255.0 for i in range(len(frames))]


@pytest.fixture(scope="module")
def vaste_frames() -> list[np.ndarray]:
    return _frames()


def _alle_looks() -> list[tuple[str, Path]]:
    from cve import looks as lookcatalogus

    uit = []
    for look in lookcatalogus.lijst():
        pad = lookcatalogus.lut_pad(look["id"])
        if pad is not None:
            uit.append((look["id"], pad))
    return uit


@pytest.mark.skipif(BINARY is None, reason="compositor niet gebouwd (cargo build --release)")
@pytest.mark.parametrize("look_id,lut", _alle_looks(), ids=lambda v: v if isinstance(v, str) else "")
def test_gpu_volgt_de_referentie(look_id, lut, vaste_frames):
    """Per look: zes frames door de GPU naast dezelfde wiskunde in numpy."""
    gpu = _door_compositor(vaste_frames, lut, 0.85, AFWERKING, SEED)
    gemiddelden, maxima = [], []
    for i, (bron, na) in enumerate(zip(vaste_frames, gpu)):
        verwacht = ref.verwerk(bron, lut=lut, sterkte=0.85, afwerking=AFWERKING, seed=SEED, frame=i)
        de = ref.delta_e2000(verwacht, na)
        gemiddelden.append(de.mean())
        maxima.append(de.max())
    assert max(gemiddelden) <= 1.0, f"{look_id}: ΔE2000 gemiddeld {max(gemiddelden):.3f}"
    assert max(maxima) <= 3.0, f"{look_id}: ΔE2000 maximaal {max(maxima):.3f}"


@pytest.mark.skipif(BINARY is None, reason="compositor niet gebouwd")
def test_zonder_look_blijft_het_beeld_staan(vaste_frames):
    """Geen LUT, geen afwerking: er mag niets veranderen op afronding na."""
    uit = _door_compositor(vaste_frames[:1], None, 1.0, {}, 0)
    de = ref.delta_e2000(vaste_frames[0], uit[0])
    assert de.max() <= 1.0, f"identiteit wijkt af: ΔE2000 max {de.max():.3f}"


@pytest.mark.skipif(BINARY is None, reason="compositor niet gebouwd")
def test_verschil_met_ffmpeg_rapporteren(vaste_frames, capsys, monkeypatch):
    """Compositor naast de ffmpeg-terugval. Alleen meten, geen eis.

    Deze twee zijn níet gelijk: ffmpeg vervaagt met een IIR-benadering, de
    compositor met een expliciete kernel, en `noise` is een andere ruisbron
    dan onze hash. Sinds 03-10-2026 doet de compositor de look en is de
    ffmpeg-keten alleen nog de terugval als het binary ontbreekt. Dit getal
    zegt dus wat die terugval kost — `cve doctor` en het render-log noemen hem.

    Vandaar `BEATCUT_COMPOSITOR=0`: zonder dat geeft `voorbeeldfilter()` een
    keten zonder look terug en meet dit niets.
    """
    monkeypatch.setenv("BEATCUT_COMPOSITOR", "0")
    from cve import paths
    from cve.edl import Afwerking, Canvas, Look
    from cve.render import voorbeeldfilter

    lut_id, lut = _alle_looks()[0]
    bron = vaste_frames[0]
    png = Path(paths.PROJECTEN).parent / ".compositor-ffmpeg-in.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(paths.ffmpeg()), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{B}x{H}", "-i", "-", "-frames:v", "1", str(png)],
        input=np.round(bron * 255).astype(np.uint8).tobytes(), check=True, timeout=120,
    )
    filters = voorbeeldfilter(
        Look(id=lut_id, sterkte=0.85), Afwerking(**AFWERKING),
        Canvas(breedte=B, hoogte=H), aanloop=0.0, breedte=0, seed=SEED,
    )
    r = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-i", str(png), "-frames:v", "1",
         "-vf", filters, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=300,
    )
    png.unlink(missing_ok=True)
    if r.returncode != 0 or len(r.stdout) != B * H * 3:
        pytest.skip(f"ffmpeg-keten draaide niet: {r.stderr.decode()[-200:]}")
    via_ffmpeg = np.frombuffer(r.stdout, np.uint8).reshape(H, B, 3).astype(np.float32) / 255.0
    via_gpu = _door_compositor([bron], lut, 0.85, AFWERKING, SEED)[0]
    de = ref.delta_e2000(via_ffmpeg, via_gpu)
    with capsys.disabled():
        print(f"\ncompositor vs ffmpeg-keten ({lut_id}): "
              f"ΔE2000 gemiddeld {de.mean():.2f}, maximaal {de.max():.2f}")


@pytest.mark.skipif(BINARY is None, reason="compositor niet gebouwd")
def test_vier_k_past_in_de_apparaatlimieten():
    """3840x2160 door de compositor. Codex-tegenlezing 03-10-2026, bevinding 15.

    `wgpu::Limits::downlevel_defaults()` zet de textuurgrens op 2048; zonder
    de limieten uit de adapter viel 4K om met "Dimension X value 3840 exceeds
    the limit of 2048" - en niet als nette fout, maar als paniek uit wgpu.
    Eén zwart frame is genoeg: het gaat om het aanmaken van het apparaat.
    """
    b, h = 3840, 2160
    r = subprocess.run(
        [str(BINARY), "--breedte", str(b), "--hoogte", str(h), "--aantal", "1",
         "--lut", "geen", "--sterkte", "1",
         "--afwerking", json.dumps({"korrel": 0.3, "gloed": 0.4, "vignet": 0.2}),
         "--seed", "7"],
        input=bytes(b * h * 4), capture_output=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr.decode()[-500:]
    assert len(r.stdout) == b * h * 4
