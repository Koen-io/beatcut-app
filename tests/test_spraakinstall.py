"""Het spraakmodel ophalen in de app (15-10-2026).

Bij de eerste echte klikronde bleek de spraakkaart in de gebouwde app dood:
geen whisper-cli, geen model, geen knop. Dit legt vast dat de kaart weet
wanneer het model op te halen is, dat het ophalen in de steunmap belandt en
dat `paths.whisper_model()` het daarna vindt.
"""

import threading

import pytest
from cve import paths, spraak, spraakinstall


@pytest.fixture
def lege_steun(tmp_path, monkeypatch):
    monkeypatch.setenv("BEATCUT_STEUN", str(tmp_path / "steun"))
    monkeypatch.setattr(paths, "VENDOR", tmp_path / "geen-vendor")
    monkeypatch.delenv("CVE_WHISPER_MODEL", raising=False)
    return tmp_path


def test_zonder_model_maar_met_binary_is_het_op_te_halen(lege_steun, monkeypatch):
    monkeypatch.setattr(paths, "whisper_bin", lambda: lege_steun / "whisper-cli")
    monkeypatch.setattr(paths, "PROJECTEN", lege_steun)
    (lege_steun / "p").mkdir()
    s = spraak.stand("p")
    assert s["kan"] is False
    assert s["model_ophaalbaar"] is True
    assert s["model_bytes"] == spraakinstall.GROOTTE


def test_zonder_binary_valt_er_niets_op_te_halen(lege_steun, monkeypatch):
    monkeypatch.setattr(paths, "whisper_bin", lambda: None)
    monkeypatch.setattr(paths, "PROJECTEN", lege_steun)
    (lege_steun / "p").mkdir()
    assert spraak.stand("p")["model_ophaalbaar"] is False


def test_ophalen_zet_het_model_waar_paths_het_vindt(lege_steun, monkeypatch):
    assert paths.whisper_model() is None
    gevraagd = {}

    def nep(url, doel, *, melder, stap, tekst, sha256=None, verwacht=0, stop=None):
        gevraagd.update(url=url, sha=sha256)
        melder(stap, verwacht, verwacht, tekst)
        doel.parent.mkdir(parents=True, exist_ok=True)
        doel.write_bytes(b"model")
        return doel

    monkeypatch.setattr(spraakinstall, "_download", nep)
    monkeypatch.setattr(spraakinstall, "RUIMTE_NODIG", 0)
    meldingen = []
    klaar = threading.Event()

    def melder(soort, data):
        meldingen.append((soort, data))
        if soort in ("klaar", "fout"):
            klaar.set()

    assert spraakinstall.in_achtergrond(melder=melder) is True
    assert klaar.wait(5)
    soorten = [s for s, _ in meldingen]
    assert soorten[-1] == "klaar", meldingen
    assert all(d["werk"] == "spraakinstall" for _, d in meldingen)
    assert gevraagd["sha"] == spraakinstall.SHA256
    assert gevraagd["url"].endswith(spraakinstall.MODEL)
    assert paths.whisper_model() == spraakinstall.modelmap() / spraakinstall.MODEL


def test_een_mislukte_download_meldt_een_fout(lege_steun, monkeypatch):
    def kapot(*a, **k):
        raise RuntimeError("geen netwerk")

    monkeypatch.setattr(spraakinstall, "_download", kapot)
    monkeypatch.setattr(spraakinstall, "RUIMTE_NODIG", 0)
    uit = []
    klaar = threading.Event()
    spraakinstall.in_achtergrond(melder=lambda s, d: (uit.append((s, d)), klaar.set() if s == "fout" else None))
    assert klaar.wait(5)
    assert uit[-1][0] == "fout" and "geen netwerk" in uit[-1][1]["fout"]
    assert paths.whisper_model() is None
