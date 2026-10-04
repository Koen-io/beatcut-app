"""Waar `compositor.binary()` zoekt, en in welke volgorde.

Dit lijkt een detail maar is er één keer duur geweest (03-10-2026, een
kwartier): `installer/uit/compositor/` stond vóór `compositor/target/release/`,
dus een verse `cargo build --release` werd stil overschaduwd door een oude
kopie. De hele testsuite draaide tegen een verouderd binary en de
overgangstests faalden onverklaarbaar. Vandaar deze poort: in de
ontwikkelboom wint wat je net gebouwd hebt.
"""

from __future__ import annotations

import os
import sys

import pytest

from cve import compositor, paths

NAAM = "beatcut-compositor.exe" if os.name == "nt" else "beatcut-compositor"


def _zet_neer(wortel, *onderdelen):
    """Maak een nep-binary op `wortel/onderdelen...` en geef het pad terug."""
    p = wortel.joinpath(*onderdelen, NAAM)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(0o755)
    return p


@pytest.fixture
def boom(tmp_path, monkeypatch):
    """Een lege ontwikkelboom als `paths.ROOT`, zonder omgevingsvariabele."""
    monkeypatch.delenv("BEATCUT_COMPOSITOR_BIN", raising=False)
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    return tmp_path


def test_een_verse_cargo_bouw_gaat_voor_de_kopie_in_installer_uit(boom):
    _zet_neer(boom, "installer", "uit", "compositor")
    vers = _zet_neer(boom, "compositor", "target", "release")
    assert compositor.binary() == vers


def test_zonder_cargo_bouw_blijft_de_kopie_in_installer_uit_gelden(boom):
    kopie = _zet_neer(boom, "installer", "uit", "compositor")
    assert compositor.binary() == kopie


def test_de_omgevingsvariabele_gaat_voor_alles(boom, monkeypatch):
    _zet_neer(boom, "installer", "uit", "compositor")
    _zet_neer(boom, "compositor", "target", "release")
    eigen = _zet_neer(boom, "elders")
    monkeypatch.setenv("BEATCUT_COMPOSITOR_BIN", str(eigen))
    assert compositor.binary() == eigen


def test_een_lege_boom_levert_niets_op(boom):
    assert compositor.binary() is None


def test_een_bevroren_app_kijkt_niet_in_de_cargo_map(boom, monkeypatch):
    """Daar staat niets in een bundel, en wie met `CVE_ROOT` naar de broncode
    wijst om een build te testen wil juist het meegeleverde binary meten."""
    meegeleverd = _zet_neer(boom, "installer", "uit", "compositor")
    _zet_neer(boom, "compositor", "target", "release")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert compositor.binary() == meegeleverd
