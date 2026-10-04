"""Het protocol tussen app en engine: één regel erin, één antwoord eruit."""

import io
import json
import subprocess
import sys

from cve import rpc
from cve.rpc import verwerk


def test_hallo_meldt_versie_en_protocol():
    a = verwerk('{"id": 7, "methode": "hallo"}')
    assert a["id"] == 7
    assert a["resultaat"]["protocol"] == 1
    assert "doctor" in a["resultaat"]["methodes"]


def test_onbekende_methode_is_een_fout_geen_crash():
    a = verwerk('{"id": 1, "methode": "bestaat-niet"}')
    assert a["fout"]["soort"] == "Protocol"


def test_kapotte_json_is_een_fout_geen_crash():
    assert verwerk("{niet json")["fout"]["soort"] == "Protocol"


def test_print_in_engine_code_lekt_niet_naar_stdout():
    """Eén losse print() in de engine mag het protocol nooit breken."""
    code = (
        "from cve import rpc\n"
        "@rpc.methode('praat')\n"
        "def _p(_):\n"
        "    print('dit hoort op stderr')\n"
        "    return 42\n"
        "rpc.draai()\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        input='{"id": 1, "methode": "praat"}\n{"id": 2, "methode": "hallo"}\n',
        capture_output=True, text=True, timeout=60,
    )
    regels = r.stdout.strip().splitlines()
    assert len(regels) == 2
    assert json.loads(regels[0]) == {"id": 1, "resultaat": 42}
    assert "dit hoort op stderr" in r.stderr


def test_protocol_schrijft_utf8_ook_op_een_stroom_die_cp1252_denkt(monkeypatch):
    """Een pijp op Windows staat standaard op cp1252.

    `José` wordt daar andere bytes dan UTF-8, en de leesdraad in Rust valt
    stil op wat hij niet kan ontcijferen. Het protocol is UTF-8 — altijd, wat
    de stroom er zelf ook van denkt.
    """
    ruw = io.BytesIO()
    monkeypatch.setattr(rpc, "_uit", io.TextIOWrapper(ruw, encoding="cp1252", newline=""))

    rpc._schrijf({"id": 1, "resultaat": {"project": "José — ñ"}})

    regel = ruw.getvalue().decode("utf-8")  # faalt op cp1252-bytes
    assert json.loads(regel)["resultaat"]["project"] == "José — ñ"


def test_bezig_meldt_werk_uit_alle_hoeken():
    """De app vraagt dit vóór het installeren van een update.

    Op Windows sluit de updater de app meteen af; loopt er dan een render,
    een analyse of een muziekgeneratie, dan is dat werk weg. Beide
    administraties (projecten en muziekgen) moeten dus meetellen.
    """
    from cve import muziekgen, projecten

    assert verwerk('{"id": 1, "methode": "bezig"}')["resultaat"] == {"bezig": False, "werk": []}

    projecten.zet_bezig("vakantie", "Blokken renderen 3/21")
    muziekgen._bezig.add("bruiloft")
    try:
        uit = verwerk('{"id": 2, "methode": "bezig"}')["resultaat"]
        assert uit["bezig"] is True
        assert uit["werk"] == [
            {"project": "vakantie", "tekst": "Blokken renderen 3/21"},
            {"project": "bruiloft", "tekst": "Muziek componeren…"},
        ]
    finally:
        projecten.zet_bezig("vakantie", None)
        muziekgen._bezig.discard("bruiloft")

    assert verwerk('{"id": 3, "methode": "bezig"}')["resultaat"]["bezig"] is False
