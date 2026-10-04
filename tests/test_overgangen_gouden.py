"""De gouden-frames-poort voor de overgangen (PLAN-v2 §4.4).

Alle veertien overgangen uit `edl.OVERGANGEN`, acht momenten per overgang,
door de échte overgangspas van de compositor — en daarnaast dezelfde wiskunde
in numpy (`ref_compositor.overgang`). De eis: ΔE2000 gemiddeld ≤ 1 en
maximaal ≤ 3, per pixel.

Dit is de overgangenkant van `test_compositor.py`, die hetzelfde doet voor
look en afwerking. Hij bewijst dat `app/shaders/overgangen.wgsl` op de GPU
rekent wat de wiskunde zegt — en dus dat de voorvertoning (die dezelfde WGSL
in de webview draait) en de export niet uiteen kunnen lopen.

Wat hij níet meet: de kadering. In de export staat het kader op de eenheid
(ffmpeg heeft de blokken al op canvasformaat gezet); in de speler zit vulmodus
en Ken Burns in `u.bronA`/`u.bronB`. Dat verschil meet
`test_overgangen_export.py` en de speler-QA.

**Waarom de A-staart in FFV1 gaat.** De compositor leest de staarten met
ffmpeg uit een bestand (`--staart`), want in de echte render komen ze daar ook
vandaan. Een gewone h264-staart zou hier de codec meten in plaats van de
shader; FFV1 op `rgba` is verliesvrij, dus wat de shader binnenkrijgt is
byte voor byte wat de test erin stopte.
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

B, H = 160, 90  # 16:9, en klein genoeg voor de numpy-tweeling per pixel
N = 8           # momenten per overgang: t = 0, 1/8 ... 7/8
SEED = 7

# Wie niet meedoet aan "op t=0 staat bron A onaangeroerd in beeld". De dips
# horen daar niet aan mee te doen, `wipe` is een bekende fout in de wachtrij.
_T0_UITZONDERING = {"dip_zwart", "dip_wit", "wipe"}


def _binary() -> Path | None:
    from cve import compositor

    return compositor.binary()


BINARY = _binary()
nodig_compositor = pytest.mark.skipif(
    BINARY is None, reason="compositor niet gebouwd (cargo build --release)"
)


def _bronnen() -> tuple[np.ndarray, np.ndarray]:
    """Twee vaste beelden: A (uitgaand) en B (inkomend).

    Vloeiend én met structuur. Vloeiend omdat de overgangen die resamplen
    (whip_pan, zoom_punch, slice, glitch) anders op een scherpe rand het
    laatste bitje van de uv-interpolatie meten in plaats van de shader; met
    structuur omdat een vlak beeld elke verschuiving verbergt.
    """
    y, x = np.mgrid[0:H, 0:B].astype(np.float64)
    u, v = x / (B - 1), y / (H - 1)
    a = np.stack([
        0.5 + 0.45 * np.sin(u * 5.0),
        0.5 + 0.45 * np.cos(v * 4.0 + 1.0),
        np.clip(0.2 + 0.7 * u * v, 0, 1),
    ], -1)
    r = np.hypot(u - 0.35, v - 0.6)
    b = np.stack([
        np.clip(0.9 - 0.8 * r, 0, 1),
        np.clip(0.15 + 0.8 * v, 0, 1),
        0.5 + 0.45 * np.sin(v * 6.0 + u * 2.0),
    ], -1)
    # Op het 8-bits raster: de GPU krijgt ze als Rgba8Unorm-texturen binnen, en
    # de tweeling hoort met precies diezelfde getallen te rekenen.
    return tuple(np.round(np.clip(f, 0, 1) * 255) / 255.0 for f in (a, b))  # type: ignore[return-value]


def _rgba(beeld: np.ndarray) -> bytes:
    q = np.round(np.clip(beeld, 0, 1) * 255).astype(np.uint8)
    return np.dstack([q, np.full((H, B, 1), 255, np.uint8)]).tobytes()


def _door_de_gpu(werk, seed: int) -> dict[str, list[np.ndarray]]:
    """Alle overgangen in één aanroep van het binary.

    Achter elkaar op één tijdlijn: overgang *k* bezet frame `k*N .. k*N+N-1`.
    Eén GPU-start en één ffmpeg voor de staarten, in plaats van veertien.
    """
    from cve import paths

    if not paths.heeft_ffmpeg():
        pytest.skip("ffmpeg niet gevonden")
    a, b = _bronnen()
    soorten = ref.O_NAMEN
    totaal = len(soorten) * N

    staart = werk / "staart.mkv"
    r = subprocess.run(
        [str(paths.ffmpeg()), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{B}x{H}", "-r", "30", "-i", "-", "-c:v", "ffv1", "-pix_fmt", "rgba",
         str(staart)],
        input=_rgba(a) * totaal, capture_output=True, timeout=300,
    )
    assert r.returncode == 0, r.stderr.decode()[-500:]
    # Verliesvrij, anders meet deze poort de codec en niet de shader.
    heen = subprocess.run(
        [str(paths.ffmpeg()), "-v", "error", "-i", str(staart),
         "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, timeout=300,
    )
    assert heen.stdout == _rgba(a) * totaal, "de staart is niet verliesvrij teruggekomen"

    lijst = [{"start": k * N, "n": N, "duur": float(N), "soort": k}
             for k in range(len(soorten))]
    (werk / "overgangen.json").write_text(json.dumps(lijst), encoding="utf-8")
    r = subprocess.run(
        [str(BINARY), "--breedte", str(B), "--hoogte", str(H), "--aantal", str(totaal),
         "--lut", "geen", "--sterkte", "1", "--afwerking", "", "--seed", str(seed),
         "--overgangen-bestand", str(werk / "overgangen.json"),
         "--staart", str(staart), "--ffmpeg", str(paths.ffmpeg()), "--fps", "30"],
        input=_rgba(b) * totaal, capture_output=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr.decode()[-500:]
    assert len(r.stdout) == totaal * B * H * 4, len(r.stdout)
    ruw = np.frombuffer(r.stdout, np.uint8).reshape(totaal, H, B, 4)
    uit: dict[str, list[np.ndarray]] = {}
    for k, naam in enumerate(soorten):
        uit[naam] = [ruw[k * N + i, :, :, :3].astype(np.float32) / 255.0 for i in range(N)]
    return uit


@pytest.fixture(scope="module")
def door_de_gpu(tmp_path_factory) -> dict[str, list[np.ndarray]]:
    """De hele reeks op `SEED`: waar de referentiemeting op staat."""
    return _door_de_gpu(tmp_path_factory.mktemp("overgangen"), SEED)


@pytest.fixture(scope="module")
def door_de_gpu_zonder_seed(tmp_path_factory) -> dict[str, list[np.ndarray]]:
    """Dezelfde reeks op effectseed 0 — de seed die de ruis op het randje zet.

    `o_ruis()` is een omkeerbare hash van zijn drie getallen, dus hij geeft
    precies 0 terug zodra die drie samen 0 zijn: band 0, as 0, seed 0. Een
    drempel van 0 betekent voor elke vergelijking "al omgeklapt", en daar liep
    `glitch` op stuk (brein-taak 20261003-181242). Een effectseed van 0 is geen
    gek geval maar de terugval zodra `edl.json` er geen heeft, dus die hoort
    even goed gemeten te worden als een willekeurige.
    """
    return _door_de_gpu(tmp_path_factory.mktemp("overgangen-seed0"), 0)


@pytest.mark.parametrize("soort", ref.O_NAMEN)
@nodig_compositor
def test_gpu_volgt_de_referentie(soort, door_de_gpu, capsys):
    """Per overgang: acht momenten door de GPU naast dezelfde wiskunde in numpy."""
    a, b = _bronnen()
    k = ref.O_NAMEN.index(soort)
    gemiddelden, maxima = [], []
    for i, na in enumerate(door_de_gpu[soort]):
        verwacht = ref.overgang(a, b, soort, i / N, frame=k * N + i, seed=SEED)
        de = ref.delta_e2000(verwacht, na)
        gemiddelden.append(float(de.mean()))
        maxima.append(float(de.max()))
    with capsys.disabled():
        print(f"\n  {soort:<11} ΔE2000 gemiddeld {max(gemiddelden):.3f}, "
              f"maximaal {max(maxima):.3f}")
    assert max(gemiddelden) <= 1.0, f"{soort}: ΔE2000 gemiddeld {max(gemiddelden):.3f}"
    assert max(maxima) <= 3.0, f"{soort}: ΔE2000 maximaal {max(maxima):.3f}"


@nodig_compositor
def test_het_snedeframe_is_nog_helemaal_a(door_de_gpu):
    """Op t=0 hoort elke overgang bron A te tonen, onaangeroerd.

    Dat is het frame waarop de snede valt: begint een overgang al met een
    vleugje B, dan springt het beeld een frame voordat de muziek dat doet.
    `dip_zwart` en `dip_wit` tellen niet mee — die horen op t=0 juist dicht
    te zijn. Eén overgang staat als bekende fout in de wachtrij en is hier
    uitgezonderd tot hij gerepareerd is: `wipe` (brein-taak 20261004-055038,
    het lichtlijntje staat op t=0 al in de linkerkolommen, want de grens begint
    op -0,015 en de zachte rand is 0,015 breed — ΔE2000 5,9).
    """
    a, _ = _bronnen()
    fout = {}
    for soort, frames in door_de_gpu.items():
        if soort in _T0_UITZONDERING:
            continue
        de = float(ref.delta_e2000(a, frames[0]).max())
        if de > 3.0:
            fout[soort] = round(de, 2)
    assert not fout, f"op t=0 al niet meer bron A: {fout}"


@nodig_compositor
def test_het_snedeframe_is_nog_helemaal_a_met_effectseed_0(door_de_gpu_zonder_seed, capsys):
    """Hetzelfde snedeframe, maar met effectseed 0 — en gemeten in codes.

    Een ΔE2000 zegt hier te weinig: het gaat niet om kleurafstand maar om
    "staat er al een stukje van B in beeld". Met effectseed 0 nam de bovenste
    band van `glitch` op t=0 al bron B (191 codes op deze twee bronnen, gemeten
    04-10-2026 voor de reparatie). De lat: geen enkel kanaal meer dan 2 codes
    van bron A af, en dat is afrondingsruimte en geen beeld.
    """
    a, _ = _bronnen()
    codes_a = np.round(np.clip(a, 0, 1) * 255).astype(np.int16)
    gemeten, fout = {}, {}
    for soort, frames in door_de_gpu_zonder_seed.items():
        if soort in _T0_UITZONDERING:
            continue
        codes = int(np.abs(np.round(frames[0] * 255).astype(np.int16) - codes_a).max())
        gemeten[soort] = codes
        if codes > 2:
            fout[soort] = codes
    with capsys.disabled():
        print("\n  t=0 bij effectseed 0, codes van bron A af: "
              + ", ".join(f"{k} {v}" for k, v in gemeten.items()))
    assert not fout, f"op t=0 al niet meer bron A (codes): {fout}"


@nodig_compositor
def test_tegenproef_de_poort_kan_echt_falen(door_de_gpu):
    """Bewijst dat de maat tanden heeft.

    Eén moment ernaast — de GPU op t=3/8 naast de tweeling op t=4/8 — en de
    poort hoort aan te slaan. Zonder deze test zou een tweeling die per ongeluk
    niets berekent er net zo groen uitzien.
    """
    a, b = _bronnen()
    k = ref.O_NAMEN.index("crossfade")
    goed = float(ref.delta_e2000(
        ref.overgang(a, b, "crossfade", 3 / N, frame=k * N + 3, seed=SEED),
        door_de_gpu["crossfade"][3]).max())
    scheef = float(ref.delta_e2000(
        ref.overgang(a, b, "crossfade", 4 / N, frame=k * N + 3, seed=SEED),
        door_de_gpu["crossfade"][3]).max())
    assert goed <= 3.0, f"het juiste moment hoort te passen: {goed:.3f}"
    assert scheef > 3.0, f"een moment ernaast glipt erdoor: {scheef:.3f}"
