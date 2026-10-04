"""Hoe de engine de compositor start: commandoregel en procesopruiming.

Twee dingen die pas bij een lange montage of een fout naar boven komen, en
daarom nooit in een gewone render te zien zijn.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

import pytest
from cve import compositor
from cve import paths
from cve.edl import Afwerking, Canvas, Look

# Windows kapt een commandoregel af op 32.767 UTF-16-code-eenheden.
WINDOWS_GRENS = 32_767


def _overgangen(aantal: int) -> list[dict]:
    """Vijf minuten montage met shots van een halve seconde."""
    return [
        {"start": i * 15, "n": 12, "duur": 12.0, "soort": i % 14}
        for i in range(aantal)
    ]


def test_zeshonderd_overgangen_passen_op_de_commandoregel(tmp_path):
    doel = tmp_path / "stil-look.mp4"
    lijst = _overgangen(600)

    # Zonder bestand zou alleen de JSON de limiet al overschrijden.
    kaal = subprocess.list2cmdline(["--overgangen", json.dumps(lijst)])
    assert len(kaal) > WINDOWS_GRENS, "testgegevens zijn te klein geworden"

    args = compositor._argumenten(
        1920, 1080, Look(id="geen", sterkte=0.0), Afwerking(), 0, 0, 0
    ) + compositor._overgangargumenten(lijst, tmp_path / "staarten.mp4", "ffmpeg", 30, doel)
    assert len(subprocess.list2cmdline(args)) < WINDOWS_GRENS

    pad = tmp_path / "stil-look-overgangen.json"
    assert str(pad) in args
    assert json.loads(pad.read_text(encoding="utf-8")) == lijst


# -- stderr van de staart-ffmpeg -------------------------------------------

# Een nep-ffmpeg die eerst zijn stderr volschrijft en pas daarna frames geeft.
# Precies wat een stapel beschadigde videopakketten doet: `-v error` laat die
# meldingen door, en 64 kB is genoeg om een pijp te vullen.
NEP_FFMPEG = """#!{python}
import sys
sys.stderr.write("x" * (1024 * 1024))
sys.stderr.flush()
sys.stdout.buffer.write(bytes({pixels} * {frames}))
sys.stdout.buffer.flush()
"""


@pytest.mark.skipif(os.name == "nt", reason="shebang-script; de structuur is gelijk")
@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_volle_stderr_van_de_staart_zet_de_compositor_niet_vast(tmp_path):
    """De keten mag niet blijven hangen als de staart-ffmpeg veel klaagt.

    Zonder eigen stderr-pijp erft de staart-ffmpeg die van de compositor, en
    die staat bij `pas_toe()` op een pijp die Python pas leest nadat alles
    klaar is. Dan wachten ze op elkaar: ffmpeg op ruimte in stderr, de
    compositor op het volgende staartframe, Python op de encoder.
    """
    b = h = 64
    pixels = b * h * 4
    frames = 4

    nep = tmp_path / "nep-ffmpeg"
    nep.write_text(NEP_FFMPEG.format(python=sys.executable, pixels=pixels, frames=frames))
    nep.chmod(0o755)

    lijst = tmp_path / "overgangen.json"
    lijst.write_text(json.dumps([{"start": 0, "n": frames, "duur": float(frames), "soort": 1}]))

    args = compositor._argumenten(
        b, h, Look(id="geen", sterkte=0.0), Afwerking(), 0, frames, 0
    ) + ["--overgangen-bestand", str(lijst), "--staart", str(tmp_path / "staarten.mp4"),
         "--ffmpeg", str(nep), "--fps", "30"]

    proc = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    # stdout wél leeglezen, stderr níet — zoals `pas_toe()` het doet.
    weg = threading.Thread(target=proc.stdout.read, daemon=True)
    weg.start()
    proc.stdin.write(bytes(pixels * frames))
    proc.stdin.close()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("de compositor liep vast op een volle stderr van de staart-ffmpeg")
    assert proc.returncode == 0, (proc.stderr.read() or b"").decode("utf-8", "replace")[-500:]


# -- opruimen bij een timeout ----------------------------------------------


@pytest.mark.skipif(not compositor.aan(), reason="geen compositor-binary")
def test_timeout_laat_geen_processen_achter(tmp_path, monkeypatch):
    """Een timeout breekt het wachten af, maar mag niets laten doordraaien.

    Drie ffmpeg's en een compositor die na een mislukte export blijven staan,
    houden de GPU, de schijf en de bronbestanden bezet.
    """
    bron = tmp_path / "bron.mp4"
    subprocess.run(
        [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=3",
         "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", str(bron)],
        check=True, capture_output=True, timeout=120,
    )

    gestart: list[subprocess.Popen] = []
    echt = subprocess.Popen

    def onthoud(*a, **k):
        p = echt(*a, **k)
        gestart.append(p)
        return p

    monkeypatch.setattr(compositor.subprocess, "Popen", onthoud)

    with pytest.raises(subprocess.TimeoutExpired):
        compositor.pas_toe(
            bron, tmp_path / "uit.mp4", Look(id="geen", sterkte=0.0), Afwerking(),
            Canvas(breedte=320, hoogte=240, fps=30), timeout=0,
        )

    # Meer dan drie: `media.video_encoder()` probeert eerst encoders uit.
    assert len(gestart) >= 3
    for p in gestart:
        assert p.poll() is not None, f"{p.args[0]} draait nog"
