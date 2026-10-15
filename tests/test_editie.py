"""De editie-naam: één plek, uit de omgeving, overal zichtbaar."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

WORTEL = Path(__file__).resolve().parents[1]


def _in_kind(env: dict[str, str], code: str) -> str:
    omgeving = {**os.environ, **env}
    omgeving.pop("BEATCUT_STEUN", None)
    omgeving.pop("CVE_PROJECTEN", None)
    uit = subprocess.run(
        [sys.executable, "-c", code],
        cwd=WORTEL / "engine",
        env=omgeving,
        capture_output=True,
        text=True,
        check=True,
    )
    return uit.stdout.strip()


def test_standaard_is_beatcut():
    assert _in_kind({"BEATCUT_APPNAAM": ""}, "from cve import editie; print(editie.NAAM)") == "BeatCut"


def test_andere_editie_bepaalt_steunmap_en_naam():
    code = (
        "from cve import editie, paths; "
        "print(editie.NAAM); print(paths.steun_map().name)"
    )
    regels = _in_kind({"BEATCUT_APPNAAM": "P-ALV Movie Maker"}, code).splitlines()
    assert regels == ["P-ALV Movie Maker", "P-ALV Movie Maker"]


def test_mapnaam_zonder_lastige_tekens():
    uit = _in_kind({"BEATCUT_APPNAAM": "Raar/Merk:X"}, "from cve import editie; print(editie.MAPNAAM)")
    assert uit == "Raar-Merk-X"


def test_hallo_meldt_de_editie():
    from cve import editie, rpc

    hallo = rpc.METHODES["hallo"]({})
    assert hallo["editie"] == editie.NAAM
    assert "steunmap" in hallo and "projecten" in hallo


def test_geen_beatcut_in_zichtbare_engine_teksten():
    """Regel 6: de naam komt uit editie.NAAM, niet uit een string-literal.

    Commentaar en docstrings mogen hem noemen; code die een melding bouwt niet.
    Uitzonderingen zijn technische namen (User-Agent, 'beatcut'-sleutels)."""
    import ast

    fouten = []
    for pad in sorted((WORTEL / "engine" / "cve").rglob("*.py")):
        if pad.name in ("editie.py", "cli.py"):  # de bron zelf, en de interne CLI
            continue
        boom = ast.parse(pad.read_text(encoding="utf-8"))
        for knoop in ast.walk(boom):
            if isinstance(knoop, ast.Constant) and isinstance(knoop.value, str):
                s = knoop.value
                if "BeatCut" in s and not s.lstrip().startswith(("'''", '"""')):
                    # Docstrings zijn ook Constant-knopen; die herken je aan de
                    # ouder, maar simpeler: een docstring heeft regeleinden en
                    # staat op kolom 0/4. Meldingen zijn één regel.
                    if "\n" in s or s.startswith("De Node die"):  # docstrings
                        continue
                    if s.startswith("BeatCut/"):  # User-Agent
                        continue
                    fouten.append(f"{pad.relative_to(WORTEL)}:{knoop.lineno}: {s[:60]!r}")
    assert fouten == [], "\n".join(fouten)
