"""Een project verwijderen via het RPC-protocol.

De prullenbak is hier een map in `tmp_path`: een test hoort niets in de echte
prullenbak van de machine achter te laten. Dat het echte `send2trash` werkt is
met de hand gemeten (zie `projectgeheugen/app-engine-brug.md`).
"""

import json
import shutil
import zipfile

import pytest
from cve import opruimen, paths, rpc
from cve import projecten as projecten_mod


@pytest.fixture
def omgeving(tmp_path, monkeypatch):
    """Projecten en prullenbak in een tijdelijke map, plus een 'origineel'
    buiten de projectmap dat nooit geraakt mag worden."""
    monkeypatch.setattr(paths, "PROJECTEN", tmp_path / "projecten")
    bak = tmp_path / "prullenbak"
    bak.mkdir()

    def nep(pad):
        # De echte prullenbak nummert een tweede ding met dezelfde naam zelf.
        doel = bak / pad.name
        while doel.exists():
            doel = doel.with_name(doel.name + "+")
        shutil.move(str(pad), str(doel))

    monkeypatch.setattr(opruimen, "_naar_prullenbak", nep)
    origineel = tmp_path / "camera" / "vakantie.mp4"
    origineel.parent.mkdir()
    origineel.write_bytes(b"o" * 5000)
    return tmp_path, bak, origineel


def _vraag(methode: str, **params):
    antwoord = rpc.verwerk(json.dumps({"id": 1, "methode": methode, "params": params}))
    assert "fout" not in antwoord, antwoord
    return antwoord["resultaat"]


def _fout(methode: str, **params) -> str:
    antwoord = rpc.verwerk(json.dumps({"id": 1, "methode": methode, "params": params}))
    return antwoord["fout"]["bericht"]


def _vul(origineel, naam: str = "proef"):
    """Een project met van elke soort iets, in bekende groottes."""
    _vraag("project.maak", naam=naam)
    _vraag("project.voegtoe", project=naam, paden=[str(origineel)])
    p = paths.PROJECTEN / naam
    (p / "muziek" / "nummer.mp3").write_bytes(b"m" * 300)
    (p / "proxies" / "C01.mp4").write_bytes(b"p" * 2000)
    (p / "cache" / "C01.wav").write_bytes(b"c" * 400)
    (p / "renders" / "proef-eind.mp4").write_bytes(b"r" * 1000)
    (p / "edl.json").write_text('{"shots": []}', encoding="utf-8")
    (p / "analysis.json").write_text('{"clips": {}}', encoding="utf-8")
    (p / "keuzes.json").write_text("[]", encoding="utf-8")
    return p


def test_omvang_meet_per_soort_wat_er_op_schijf_staat(omgeving):
    _, _, origineel = omgeving
    _vul(origineel)

    uit = _vraag("project.omvang", project="proef")

    s = uit["soorten"]
    assert s["kopieen"] == {"bytes": 5000, "bestanden": 1}
    assert s["muziek"] == {"bytes": 300, "bestanden": 1}
    assert s["exports"] == {"bytes": 1000, "bestanden": 1}
    # herkomst.json: waar de originelen stonden; hoort bij het project zelf.
    herkomst = (paths.PROJECTEN / "proef" / "herkomst.json").stat().st_size
    assert s["werk"]["bytes"] == 2000 + 400 + len('{"shots": []}') + len('{"clips": {}}') + 2 + herkomst
    assert uit["totaal"] == sum(x["bytes"] for x in s.values())
    assert uit["aantal_clips"] == 1
    assert uit["kopie"]["proxies"] == 2000
    assert uit["bezig"] is None


def test_alles_weg_gaat_als_een_map_naar_de_prullenbak_en_het_origineel_blijft(omgeving):
    _, bak, origineel = omgeving
    _vul(origineel)

    uit = _vraag("project.verwijder", project="proef", weg=["kopieen", "muziek", "exports"])

    assert not (paths.PROJECTEN / "proef").exists()
    assert [s["naam"] for s in _vraag("projecten")] == []
    # Niet hard weg: alles is terug te vinden, als één ding.
    assert [q.name for q in bak.iterdir()] == ["proef"]
    assert (bak / "proef" / "bronnen" / "vakantie.mp4").exists()
    assert uit["bewaard"] is None
    assert uit["vrijgemaakt"] == _som(bak / "proef")
    # Regel 4: het bestand van de gebruiker zelf is niet aangeraakt.
    assert origineel.read_bytes() == b"o" * 5000


def _som(pad) -> int:
    return sum(q.stat().st_size for q in pad.rglob("*") if q.is_file())


def test_wat_niet_in_weg_staat_verhuist_naar_bewaard_en_is_geen_project(omgeving):
    _, bak, origineel = omgeving
    _vul(origineel)

    uit = _vraag("project.verwijder", project="proef", weg=["kopieen"])

    bewaard = paths.PROJECTEN / "_Bewaard" / "proef"
    assert uit["bewaard"] == str(bewaard)
    assert (bewaard / "renders" / "proef-eind.mp4").read_bytes() == b"r" * 1000
    assert (bewaard / "muziek" / "nummer.mp3").exists()
    assert not (bewaard / "bronnen").exists()
    assert (bak / "proef" / "bronnen" / "vakantie.mp4").exists()
    assert not (bak / "proef" / "renders").exists()
    # De bewaarmap mag nooit als project in de lijst opduiken.
    assert _vraag("projecten") == []
    assert uit["vrijgemaakt"] == _som(bak / "proef")


def test_een_tweede_project_met_dezelfde_naam_overschrijft_het_bewaarde_niet(omgeving):
    _, _, origineel = omgeving
    _vul(origineel)
    _vraag("project.verwijder", project="proef", weg=[])
    _vul(origineel)

    uit = _vraag("project.verwijder", project="proef", weg=[])

    assert uit["bewaard"].endswith("proef-2")
    assert (paths.PROJECTEN / "_Bewaard" / "proef" / "renders" / "proef-eind.mp4").exists()


def test_weigert_tijdens_een_render_en_laat_alles_staan(omgeving):
    _, bak, origineel = omgeving
    p = _vul(origineel)
    projecten_mod.zet_bezig("proef", "Renderen 40%")
    try:
        assert _vraag("project.omvang", project="proef")["bezig"] == "Renderen 40%"
        bericht = _fout("project.verwijder", project="proef", weg=["kopieen"])
    finally:
        projecten_mod.zet_bezig("proef", None)

    assert "nog bezig" in bericht and "Renderen 40%" in bericht
    assert (p / "bronnen" / "vakantie.mp4").exists()
    assert list(bak.iterdir()) == []
    assert not (paths.PROJECTEN / "_Bewaard").exists()


def test_weigert_tijdens_muziek_componeren(omgeving, monkeypatch):
    from cve import muziekgen

    _, bak, origineel = omgeving
    _vul(origineel)
    monkeypatch.setattr(muziekgen, "is_bezig", lambda project: project == "proef")

    assert "nog bezig" in _fout("project.verwijder", project="proef")
    assert list(bak.iterdir()) == []


def test_na_het_verwijderen_is_het_project_niet_meer_bezig(omgeving):
    _, _, origineel = omgeving
    _vul(origineel)
    _vraag("project.verwijder", project="proef")
    assert projecten_mod.is_bezig("proef") is None


def test_kopie_is_terug_te_lezen_als_project(omgeving):
    tmp, bak, origineel = omgeving
    _vul(origineel)
    doel = tmp / "elders" / "proef-kopie"
    doel.parent.mkdir()

    uit = _vraag("project.verwijder", project="proef", kopie=str(doel), kopie_proxies=True)

    zip_pad = doel.with_name("proef-kopie.zip")
    assert uit["kopie"] == str(zip_pad)
    with zipfile.ZipFile(zip_pad) as z:
        namen = set(z.namelist())
        manifest = json.loads(z.read("beatcut-kopie.json"))
    assert {"edl.json", "analysis.json", "keuzes.json", "muziek/nummer.mp3",
            "proxies/C01.mp4"} <= namen
    # De grote video's gaan niet mee, maar staan wel bij naam in het manifest.
    assert not any(n.startswith(("bronnen/", "renders/", "cache/")) for n in namen)
    # ...en mét de plek waar het origineel stond, zodat terugzetten ze terugvindt.
    assert manifest["bronnen"] == [
        {"naam": "vakantie.mp4", "bytes": 5000, "pad": str(origineel.resolve())}
    ]
    assert not (paths.PROJECTEN / "proef").exists()

    terug = _vraag("project.terugzetten", pad=str(zip_pad))

    assert terug["naam"] == "proef" and terug["heeft_montage"] and terug["heeft_muziek"]
    p = paths.PROJECTEN / "proef"
    # Het origineel staat nog waar het stond: dan is de clip er meteen weer.
    assert terug["gekoppeld"] == ["vakantie.mp4"] and terug["ontbreekt"] == []
    assert terug["aantal_clips"] == 1
    assert (p / "bronnen" / "vakantie.mp4").read_bytes() == origineel.read_bytes()
    assert origineel.read_bytes() == b"o" * 5000
    assert (p / "edl.json").read_text(encoding="utf-8") == '{"shots": []}'
    assert (p / "proxies" / "C01.mp4").read_bytes() == b"p" * 2000


def test_kopie_zonder_proxies_laat_ze_weg(omgeving):
    tmp, _, origineel = omgeving
    _vul(origineel)
    opruimen.maak_kopie("proef", tmp / "klein.zip")
    with zipfile.ZipFile(tmp / "klein.zip") as z:
        assert not any(n.startswith("proxies/") for n in z.namelist())


def test_mislukt_de_kopie_dan_wordt_er_niets_verwijderd(omgeving):
    tmp, bak, origineel = omgeving
    p = _vul(origineel)

    bericht = _fout("project.verwijder", project="proef",
                    kopie=str(tmp / "bestaat-niet" / "kopie.zip"))

    assert bericht
    assert (p / "edl.json").exists() and (p / "bronnen" / "vakantie.mp4").exists()
    assert list(bak.iterdir()) == []
    assert projecten_mod.is_bezig("proef") is None


def test_kopie_in_de_projectmap_zelf_wordt_geweigerd(omgeving):
    _, _, origineel = omgeving
    p = _vul(origineel)
    assert "buiten de projectmap" in _fout("project.verwijder", project="proef",
                                           kopie=str(p / "kopie.zip"))
    assert p.exists()


def test_terugzetten_overschrijft_geen_bestaand_project(omgeving):
    tmp, _, origineel = omgeving
    _vul(origineel)
    opruimen.maak_kopie("proef", tmp / "k.zip")
    assert _vraag("project.terugzetten", pad=str(tmp / "k.zip"))["naam"] == "proef-2"
    assert (paths.PROJECTEN / "proef" / "bronnen" / "vakantie.mp4").exists()


def test_terugzetten_weigert_een_zip_die_buiten_de_map_wil_schrijven(omgeving):
    tmp, _, _ = omgeving
    paths.PROJECTEN.mkdir()
    kwaad = tmp / "kwaad.zip"
    with zipfile.ZipFile(kwaad, "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps({"soort": "beatcut-projectkopie", "project": "x"}))
        z.writestr("../../ontsnapt.txt", "nee")
    assert "onveilig pad" in _fout("project.terugzetten", pad=str(kwaad))
    assert not (tmp / "ontsnapt.txt").exists()


def test_terugzetten_weigert_een_gewone_zip(omgeving):
    tmp, _, _ = omgeving
    with zipfile.ZipFile(tmp / "foto.zip", "w") as z:
        z.writestr("a.txt", "hoi")
    assert "geen kopie" in _fout("project.terugzetten", pad=str(tmp / "foto.zip"))


@pytest.mark.parametrize("naam", ["", "..", "../camera", "_Bewaard", ".verborgen", "bestaat-niet"])
def test_alleen_een_echt_project_kan_weg(omgeving, naam):
    _, bak, origineel = omgeving
    _vul(origineel)
    (paths.PROJECTEN / "_Bewaard").mkdir()
    (paths.PROJECTEN / ".verborgen").mkdir()

    antwoord = rpc.verwerk(json.dumps(
        {"id": 1, "methode": "project.verwijder", "params": {"project": naam}}))

    assert "fout" in antwoord
    assert origineel.exists() and (paths.PROJECTEN / "proef").exists()
    assert list(bak.iterdir()) == []


def test_kan_de_prullenbak_niet_dan_staat_het_project_er_nog_heel(omgeving, monkeypatch):
    _, _, origineel = omgeving
    p = _vul(origineel)

    def stuk(pad):
        raise OSError("geen prullenbak op deze schijf")

    monkeypatch.setattr(opruimen, "_naar_prullenbak", stuk)

    bericht = _fout("project.verwijder", project="proef", weg=["kopieen"])

    assert "niets definitief verwijderd" in bericht
    # Wat al naar _Bewaard was verhuisd staat weer op zijn plek.
    assert (p / "renders" / "proef-eind.mp4").exists() and (p / "muziek" / "nummer.mp3").exists()
    assert not (paths.PROJECTEN / "_Bewaard" / "proef").exists()
    assert projecten_mod.is_bezig("proef") is None


def test_een_koppeling_naar_buiten_telt_niet_mee_en_het_doel_blijft(omgeving):
    tmp, bak, origineel = omgeving
    p = _vul(origineel)
    (p / "bronnen" / "link.mp4").symlink_to(origineel)

    assert _vraag("project.omvang", project="proef")["soorten"]["kopieen"]["bytes"] == 5000
    _vraag("project.verwijder", project="proef")

    assert origineel.read_bytes() == b"o" * 5000


def test_kopie_in_de_projectmap_via_een_omweg_wordt_ook_geweigerd(omgeving):
    """Op de Mac is /tmp een koppeling naar /private/tmp: hetzelfde pad, anders
    geschreven. De controle moet naar de echte plek kijken."""
    tmp, _, origineel = omgeving
    p = _vul(origineel)
    (tmp / "omweg").symlink_to(p)
    assert "buiten de projectmap" in _fout("project.verwijder", project="proef",
                                           kopie=str(tmp / "omweg" / "kopie.zip"))
    assert p.exists()


# ---------------------------------------------------------------- terugzetten


def _kopie(tmp, origineel, *, proxies: bool = False, naam: str = "proef"):
    """Een project dat weg is, en de kopie die ervan over is."""
    _vul(origineel, naam)
    zip_pad = tmp / "kopie.zip"
    _vraag("project.verwijder", project=naam, kopie=str(zip_pad), kopie_proxies=proxies)
    return zip_pad


def test_vooraf_zien_wat_er_in_de_kopie_zit_zonder_iets_te_schrijven(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel, proxies=True)

    k = _vraag("project.kopie", pad=str(zip_pad))

    assert k["project"] == "proef" and k["naam"] == "proef" and k["bezet"] is False
    assert k["aantal_clips"] == 1 and k["proxies"] is True
    assert k["heeft_montage"] is True and k["heeft_muziek"] is True
    assert k["bytes"] == zip_pad.stat().st_size and k["uitgepakt"] > 2000
    assert k["gemaakt"].startswith("20")
    assert k["bronnen"] == [{
        "naam": "vakantie.mp4", "bytes": 5000,
        "oud": str(origineel.resolve()), "pad": str(origineel.resolve()),
    }]
    assert not (paths.PROJECTEN / "proef").exists()


def test_bestaat_de_naam_al_dan_stelt_de_kopie_een_andere_voor(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel)
    _vraag("project.maak", naam="proef")
    _vraag("project.maak", naam="proef-2")

    k = _vraag("project.kopie", pad=str(zip_pad))
    assert (k["naam"], k["bezet"]) == ("proef-3", True)
    # Een eigen naam wordt net zo opgeschoond als bij een nieuw project.
    k = _vraag("project.kopie", pad=str(zip_pad), naam="Zomer 2026!")
    assert (k["naam"], k["bezet"]) == ("zomer-2026", False)

    terug = _vraag("project.terugzetten", pad=str(zip_pad), naam="Zomer 2026!")
    assert terug["naam"] == "zomer-2026"
    assert not (paths.PROJECTEN / "proef" / "edl.json").exists()


def test_is_het_origineel_weg_dan_ontbreekt_de_clip_en_komt_het_project_toch_terug(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel)
    origineel.unlink()

    k = _vraag("project.kopie", pad=str(zip_pad))
    assert k["bronnen"][0]["pad"] is None and k["bronnen"][0]["oud"]

    terug = _vraag("project.terugzetten", pad=str(zip_pad))
    assert terug["ontbreekt"] == ["vakantie.mp4"] and terug["gekoppeld"] == []
    assert terug["heeft_montage"] and terug["aantal_clips"] == 0
    # Niets om in te lezen: een ronde zou de teruggezette ingest leegschrijven.
    assert terug["verwerken"] is False


def test_een_ander_bestand_met_dezelfde_naam_is_niet_het_origineel(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel)
    origineel.write_bytes(b"x" * 4999)

    assert _vraag("project.kopie", pad=str(zip_pad))["bronnen"][0]["pad"] is None


def test_verhuisde_videos_zijn_opnieuw_aan_te_wijzen_per_map_of_per_bestand(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel)
    nieuw = tmp / "archief" / "2026" / "VAKANTIE.MP4"
    nieuw.parent.mkdir(parents=True)
    origineel.rename(nieuw)
    (nieuw.parent / "iets-anders.mp4").write_bytes(b"z" * 5000)

    # Een map: BeatCut zoekt er zelf in, ook dieper, op naam en grootte.
    k = _vraag("project.kopie", pad=str(zip_pad), zoek=[str(tmp / "archief")])
    assert k["bronnen"][0]["pad"] == str(nieuw)
    # Een los bestand kan ook.
    k = _vraag("project.kopie", pad=str(zip_pad), zoek=[str(nieuw)])
    assert k["bronnen"][0]["pad"] == str(nieuw)

    terug = _vraag("project.terugzetten", pad=str(zip_pad), zoek=[str(tmp / "archief")])
    assert terug["gekoppeld"] == ["vakantie.mp4"]
    # Onder de naam die de montage kent, niet onder die van de nieuwe plek.
    assert (paths.PROJECTEN / "proef" / "bronnen" / "vakantie.mp4").read_bytes() == b"o" * 5000
    assert nieuw.exists()
    # En de volgende kopie weet de nieuwe plek.
    assert projecten_mod.herkomst("proef")["vakantie.mp4"] == str(nieuw.resolve())


def test_zonder_voorvertoningen_vraagt_terugzetten_om_opnieuw_inlezen(omgeving):
    tmp, _, origineel = omgeving
    _vul(origineel)
    p = paths.PROJECTEN / "proef"
    (p / "ingest.json").write_text(json.dumps(
        {"clips": [{"id": "C01", "bestand": "vakantie.mp4", "proxy": "C01.mp4"}]}), encoding="utf-8")
    assert projecten_mod.moet_inlezen("proef") is False
    met, zonder = tmp / "met.zip", tmp / "zonder.zip"
    opruimen.maak_kopie("proef", met, proxies=True)
    opruimen.maak_kopie("proef", zonder)

    assert _vraag("project.terugzetten", pad=str(met))["verwerken"] is False
    assert _vraag("project.terugzetten", pad=str(zonder))["verwerken"] is True


def test_een_kopie_van_een_windows_pc_struikelt_niet_over_zijn_paden(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = tmp / "win.zip"
    with zipfile.ZipFile(zip_pad, "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps({
            "soort": "beatcut-projectkopie", "versie": 1, "project": "ski",
            "bronnen": [{"naam": "piste.mp4", "bytes": 5000,
                         "pad": "D:\\Video\\2026\\vakantie.mp4"}],
        }))
        z.writestr("edl.json", "{}")

    k = _vraag("project.kopie", pad=str(zip_pad))
    assert k["bronnen"][0]["pad"] is None
    # De clip heette op de camera anders dan in het project: beide namen tellen.
    k = _vraag("project.kopie", pad=str(zip_pad), zoek=[str(origineel.parent)])
    assert k["bronnen"][0]["pad"] == str(origineel)
    terug = _vraag("project.terugzetten", pad=str(zip_pad), zoek=[str(origineel.parent)])
    assert (paths.PROJECTEN / "ski" / "bronnen" / "piste.mp4").exists() and terug["gekoppeld"] == ["piste.mp4"]


@pytest.mark.parametrize("naam", ["../ontsnapt.mp4", "map/clip.mp4", "..\\weg.mp4", "geen-video.sh", ""])
def test_een_bron_met_een_vreemde_naam_wordt_nergens_neergezet(omgeving, naam):
    tmp, _, origineel = omgeving
    zip_pad = tmp / "kwaad.zip"
    with zipfile.ZipFile(zip_pad, "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps({
            "soort": "beatcut-projectkopie", "project": "x",
            "bronnen": [{"naam": naam, "bytes": 5000, "pad": str(origineel)}],
        }))
    assert _vraag("project.kopie", pad=str(zip_pad))["bronnen"] == []
    _vraag("project.terugzetten", pad=str(zip_pad))
    assert list((paths.PROJECTEN / "x" / "bronnen").iterdir()) == []
    assert not (paths.PROJECTEN / "ontsnapt.mp4").exists()


def test_een_kapot_of_vreemd_bestand_krijgt_een_uitleg_en_laat_niets_achter(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = _kopie(tmp, origineel, proxies=True)

    (tmp / "foto.zip").write_bytes(b"dit is geen zip")
    for methode in ("project.kopie", "project.terugzetten"):
        assert "geen .zip" in _fout(methode, pad=str(tmp / "foto.zip"))
        assert "is er niet" in _fout(methode, pad=str(tmp / "weg.zip"))

    # Eén byte omgegooid midden in een voorvertoning: de zip opent nog wel.
    ruw = bytearray(zip_pad.read_bytes())
    plek = ruw.index(b"p" * 100) + 50
    ruw[plek] ^= 0xFF
    (tmp / "stuk.zip").write_bytes(bytes(ruw))
    assert "beschadigd" in _fout("project.terugzetten", pad=str(tmp / "stuk.zip"))
    # Geen half project in de lijst.
    assert not (paths.PROJECTEN / "proef").exists()
    assert _vraag("projecten") == []


def test_een_kopie_van_een_nieuwere_beatcut_wordt_niet_half_begrepen(omgeving):
    tmp, _, _ = omgeving
    with zipfile.ZipFile(tmp / "later.zip", "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps(
            {"soort": "beatcut-projectkopie", "versie": 2, "project": "x"}))
    assert "nieuwere BeatCut" in _fout("project.kopie", pad=str(tmp / "later.zip"))
    assert "nieuwere BeatCut" in _fout("project.terugzetten", pad=str(tmp / "later.zip"))


def test_een_onveilig_pad_in_de_zip_laat_geen_half_project_achter(omgeving):
    tmp, _, _ = omgeving
    kwaad = tmp / "kwaad.zip"
    with zipfile.ZipFile(kwaad, "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps({"soort": "beatcut-projectkopie", "project": "x"}))
        z.writestr("edl.json", "{}")
        z.writestr("../../ontsnapt.txt", "nee")
    assert "onveilig pad" in _fout("project.terugzetten", pad=str(kwaad))
    assert not (paths.PROJECTEN / "x").exists()


def test_importeren_onthoudt_waar_het_origineel_stond(omgeving):
    _, _, origineel = omgeving
    _vul(origineel)
    assert projecten_mod.herkomst("proef") == {"vakantie.mp4": str(origineel.resolve())}


# ------------------------------------------- ontbrekende video's later erbij
# Uit de tegenlezing door Codex (04-10-2026): "sleep ze er later in" ging via
# de gewone import, en die weet niets van de namen die de montage kent.


def _twee_kaartjes(tmp):
    """Twee camerakaartjes met elk een IMG_0001.MOV, in het project als
    IMG_0001.MOV en IMG_0001-2.MOV; daarna weg, met een kopie, en de
    originelen verhuisd. Geeft (zip, waar A nu staat, waar B nu staat)."""
    a, b = tmp / "kaart-a" / "IMG_0001.MOV", tmp / "kaart-b" / "IMG_0001.MOV"
    for pad, inhoud in ((a, b"a" * 5000), (b, b"b" * 6000)):
        pad.parent.mkdir()
        pad.write_bytes(inhoud)
    _vraag("project.maak", naam="proef")
    _vraag("project.voegtoe", project="proef", paden=[str(a)])
    _vraag("project.voegtoe", project="proef", paden=[str(b)])
    p = paths.PROJECTEN / "proef"
    assert (p / "bronnen" / "IMG_0001-2.MOV").read_bytes() == b"b" * 6000
    (p / "ingest.json").write_text(json.dumps({"clips": [
        {"id": "C01", "bestand": "IMG_0001-2.MOV", "proxy": "C01.mp4"},
        {"id": "C02", "bestand": "IMG_0001.MOV", "proxy": "C02.mp4"},
    ]}), encoding="utf-8")
    zip_pad = tmp / "kopie.zip"
    _vraag("project.verwijder", project="proef", kopie=str(zip_pad))
    a2, b2 = tmp / "nieuw-a" / "IMG_0001.MOV", tmp / "nieuw-b" / "IMG_0001.MOV"
    for oud, nieuw in ((a, a2), (b, b2)):
        nieuw.parent.mkdir()
        oud.rename(nieuw)
    return zip_pad, a2, b2


def test_later_ingesleepte_videos_komen_onder_de_naam_die_de_montage_kent(omgeving):
    tmp, _, _ = omgeving
    zip_pad, a, b = _twee_kaartjes(tmp)
    terug = _vraag("project.terugzetten", pad=str(zip_pad))
    assert terug["ontbreekt"] == ["IMG_0001-2.MOV", "IMG_0001.MOV"]
    assert _vraag("projecten")[0]["ontbreekt"] == ["IMG_0001-2.MOV", "IMG_0001.MOV"]

    # In omgekeerde volgorde: eerst de clip die in het project "-2" heet.
    uit = _vraag("project.voegtoe", project="proef", paden=[str(b)])
    assert uit["bestanden"][0]["naam"] == "IMG_0001-2.MOV"
    assert uit["status"]["ontbreekt"] == ["IMG_0001.MOV"]
    _vraag("project.voegtoe", project="proef", paden=[str(a)])

    bronnen = paths.PROJECTEN / "proef" / "bronnen"
    assert (bronnen / "IMG_0001.MOV").read_bytes() == b"a" * 5000
    assert (bronnen / "IMG_0001-2.MOV").read_bytes() == b"b" * 6000
    assert _vraag("projecten")[0]["ontbreekt"] == []


def test_een_andere_video_neemt_de_naam_van_een_ontbrekende_niet_in(omgeving):
    tmp, _, _ = omgeving
    zip_pad, _, _ = _twee_kaartjes(tmp)
    _vraag("project.terugzetten", pad=str(zip_pad))
    vreemd = tmp / "kaart-c" / "IMG_0001.MOV"
    vreemd.parent.mkdir()
    vreemd.write_bytes(b"c" * 777)

    uit = _vraag("project.voegtoe", project="proef", paden=[str(vreemd)])

    assert uit["bestanden"][0]["naam"] == "IMG_0001-3.MOV"
    assert uit["status"]["ontbreekt"] == ["IMG_0001-2.MOV", "IMG_0001.MOV"]


def test_zolang_er_videos_ontbreken_wordt_er_niets_opnieuw_ingelezen(omgeving):
    tmp, _, _ = omgeving
    zip_pad, a, _ = _twee_kaartjes(tmp)
    _vraag("project.terugzetten", pad=str(zip_pad))
    ingest = paths.PROJECTEN / "proef" / "ingest.json"
    voor = ingest.read_bytes()
    _vraag("project.voegtoe", project="proef", paden=[str(a)])

    start = _vraag("project.verwerk", project="proef")

    assert start["gestart"] is False and start["wacht_op"] == ["IMG_0001-2.MOV"]
    assert projecten_mod.is_bezig("proef") is None
    assert ingest.read_bytes() == voor


def test_verder_zonder_de_ontbrekende_videos_is_een_eigen_keuze(omgeving):
    tmp, _, _ = omgeving
    zip_pad, _, _ = _twee_kaartjes(tmp)
    _vraag("project.terugzetten", pad=str(zip_pad))

    na = _vraag("project.zonder_ontbrekend", project="proef")

    assert na["ontbreekt"] == []
    assert not (paths.PROJECTEN / "proef" / "ontbreekt.json").exists()


def test_een_lijst_ontbrekende_videos_uit_een_zip_van_buiten_schrijft_niet_buiten_bronnen(omgeving):
    tmp, _, origineel = omgeving
    zip_pad = tmp / "kwaad.zip"
    with zipfile.ZipFile(zip_pad, "w") as z:
        z.writestr("beatcut-kopie.json", json.dumps({"soort": "beatcut-projectkopie", "project": "x"}))
        z.writestr("ontbreekt.json", json.dumps({
            "../../ontsnapt.mp4": {"bytes": 5000, "oud": str(origineel)},
            "goed.mp4": {"bytes": "veel", "oud": None},
            "ook-goed.mp4": {"bytes": 5000, "oud": str(origineel)},
        }))
    terug = _vraag("project.terugzetten", pad=str(zip_pad))
    assert terug["ontbreekt"] == ["ook-goed.mp4"]

    _vraag("project.voegtoe", project="x", paden=[str(origineel)])
    assert sorted(q.name for q in (paths.PROJECTEN / "x" / "bronnen").iterdir()) == ["ook-goed.mp4"]
    assert not (tmp / "ontsnapt.mp4").exists()


def test_twee_videos_met_dezelfde_naam_en_grootte_krijgen_elk_hun_eigen_bestand(omgeving):
    """Codex 04-10-2026: de zoekindex hield per naam+grootte één bestand vast,
    en koppelde beide clips daaraan — ook als beide originelen er nog stonden."""
    tmp, _, _ = omgeving
    a, b = tmp / "kaart-a" / "IMG_0001.MOV", tmp / "kaart-b" / "IMG_0001.MOV"
    for pad, teken in ((a, b"a"), (b, b"b")):
        pad.parent.mkdir()
        pad.write_bytes(teken * 5000)
    _vraag("project.maak", naam="proef")
    _vraag("project.voegtoe", project="proef", paden=[str(a), str(b)])
    zip_pad = tmp / "kopie.zip"
    _vraag("project.verwijder", project="proef", kopie=str(zip_pad))

    # Beide originelen staan er nog, en de gebruiker wijst óók de bovenliggende
    # map aan: het bekende pad gaat voor wat de zoektocht toevallig eerst vond.
    _vraag("project.terugzetten", pad=str(zip_pad), zoek=[str(tmp)])
    bronnen = paths.PROJECTEN / "proef" / "bronnen"
    assert (bronnen / "IMG_0001.MOV").read_bytes() == b"a" * 5000
    assert (bronnen / "IMG_0001-2.MOV").read_bytes() == b"b" * 5000

    # Beide verhuisd: elk gevonden bestand hoort bij hoogstens één clip.
    for oud in (a, b):
        nieuw = tmp / "archief" / oud.parent.name / oud.name
        nieuw.parent.mkdir(parents=True)
        oud.rename(nieuw)
    k = _vraag("project.kopie", pad=str(zip_pad), zoek=[str(tmp / "archief")])
    assert len({bron["pad"] for bron in k["bronnen"]}) == 2
    # Eén bestand gevonden voor twee clips: dan ontbreekt er één, in plaats
    # van dat hetzelfde beeld er twee keer in komt.
    k = _vraag("project.kopie", pad=str(zip_pad), zoek=[str(tmp / "archief" / "kaart-a")])
    assert [bron["pad"] is None for bron in k["bronnen"]].count(True) == 1


def test_mislukt_een_import_halverwege_dan_is_de_herkomst_van_wat_er_al_stond_bewaard(omgeving, monkeypatch):
    """Codex 04-10-2026: de herkomst werd pas na de hele import geschreven."""
    tmp, _, origineel = omgeving
    tweede = tmp / "camera" / "tweede.mp4"
    tweede.write_bytes(b"t" * 100)
    _vraag("project.maak", naam="proef")
    echt = shutil.copy2

    def struikel(bron, doel):
        if "tweede" in str(bron):
            raise OSError("schijf vol")
        return echt(bron, doel)

    monkeypatch.setattr(projecten_mod.shutil, "copy2", struikel)
    assert "schijf vol" in _fout("project.voegtoe", project="proef", paden=[str(origineel), str(tweede)])

    assert projecten_mod.herkomst("proef") == {"vakantie.mp4": str(origineel.resolve())}


def test_gegenereerde_muziekvarianten_gaan_mee_in_de_kopie_en_komen_terug(omgeving):
    """Codex 04-10-2026: alleen `muziek/*.mp3` ging mee; de varianten in
    `muziek/gegenereerd/` waren na het legen van de prullenbak voorgoed weg."""
    tmp, _, origineel = omgeving
    p = _vul(origineel)
    gen = p / "muziek" / "gegenereerd"
    gen.mkdir()
    (gen / "variant-2.wav").write_bytes(b"w" * 700)
    (gen / "variant-2.json").write_text('{"genre": "house"}', encoding="utf-8")
    (gen / ".DS_Store").write_bytes(b"x")
    verwacht = _vraag("project.omvang", project="proef")["kopie"]["basis"]
    assert verwacht >= 700 + 300

    zip_pad = tmp / "kopie.zip"
    _vraag("project.verwijder", project="proef", kopie=str(zip_pad))
    with zipfile.ZipFile(zip_pad) as z:
        namen = set(z.namelist())
    assert {"muziek/nummer.mp3", "muziek/gegenereerd/variant-2.wav",
            "muziek/gegenereerd/variant-2.json"} <= namen
    assert "muziek/gegenereerd/.DS_Store" not in namen

    _vraag("project.terugzetten", pad=str(zip_pad))
    assert (paths.PROJECTEN / "proef" / "muziek" / "gegenereerd" / "variant-2.wav").read_bytes() == b"w" * 700
