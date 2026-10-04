"""De Look-stap: catalogus, keuze, render en het voorbeeldbeeld.

De gouden-frames-poort uit PLAN-v2 §4.4 staat niet hier maar in
`test_gouden_frames.py`: zes beelden × zes looks hebben hun eigen project met
zes clips nodig. Hier blijven de catalogus, de keuze, de render en de cache.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from cve import looks, paths, render as render_mod
from cve.edl import EDL, Afwerking, Canvas, Look, Overgang, VideoBlok
from cve.review import _frames

from test_rpc_montage import _maak_clip
from test_rpc_project import _vraag, nodig_ffmpeg

# Wat de opdracht als eindproef noemt: Blockbuster op 85 %, met de afwerking
# die `looks.json` bij die look voorstelt.
LOOK = "blockbuster"
STERKTE = 0.85
AFWERKING = {"korrel": 0.15, "halation": 0.20, "gloed": 0.15, "vignet": 0.35}

# De EDL die beide paden delen. Eén blok, geen zoom en geen overgang: dan is
# het enige verschil tussen het voorbeeld en de render de look zelf, en meet de
# vergelijking wat hij hoort te meten.
BRON_START = 3.0
BLOK_FRAMES = 30


@pytest.fixture(scope="module")
def lookproject(tmp_path_factory):
    """Eén project met één clip en een EDL van één blok. Geen analyse nodig."""
    if not paths.heeft_ffmpeg():
        pytest.skip("ffmpeg/ffprobe niet gevonden")
    basis = tmp_path_factory.mktemp("looks")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "PROJECTEN", basis / "projecten")
        _vraag("project.maak", naam="look")
        camera = basis / "camera"
        camera.mkdir()
        bron = camera / "clip-1.mp4"
        _maak_clip(bron, "null")
        _vraag("project.voegtoe", project="look", paden=[str(bron)])

        # Een proxy met een vaste naam, zodat zowel de render (modus preview)
        # als `looks.voorbeeld()` precies hetzelfde bestand gebruiken.
        pdir = paths.project_dir("look")
        proxy = pdir / "proxies" / "C01.mp4"
        subprocess.run(
            [str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(bron), "-vf", "scale=-2:360", "-c:v", "mpeg4", "-q:v", "3",
             "-an", str(proxy)],
            check=True, capture_output=True, timeout=300,
        )
        yield "look", pdir, proxy


def _edl(project: str, look: Look, afw: Afwerking) -> EDL:
    edl = EDL(project=project, canvas=Canvas(breedte=640, hoogte=360, fps=30))
    edl.look = look
    edl.afwerking = afw
    edl.video = [
        VideoBlok(
            id="B01", clip="C01", bestand="clip-1.mp4",
            bron_start=BRON_START, duur=BLOK_FRAMES / 30, tijdlijn_start=0.0,
            frames=BLOK_FRAMES, vulmodus="vul", zoom="geen",
            overgang_in=Overgang(soort="snede", duur=0.0),
        )
    ]
    return edl


def _rgb(pad: Path, frame: int = 0) -> np.ndarray:
    """Eén frame als (h, b, 3) float-array. Via ffmpeg, dus zonder extra deps."""
    r = subprocess.run(
        [str(paths.ffmpeg()), "-hide_banner", "-loglevel", "error",
         "-i", str(pad), "-vf", f"select='eq(n\\,{frame})'", "-vsync", "0",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=120,
    )
    b, h = _maat(pad)
    return np.frombuffer(r.stdout, dtype=np.uint8)[: h * b * 3].reshape(h, b, 3).astype(float)


def _maat(pad: Path) -> tuple[int, int]:
    """Breedte en hoogte via ffprobe — werkt ook op een JPG, waar `media.probe`
    een videoduur verwacht."""
    r = subprocess.run(
        [str(paths.ffprobe()), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(pad)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    b, h = r.stdout.strip().split("x")[:2]
    return int(b), int(h)


# -- catalogus en keuze ----------------------------------------------------


@nodig_ffmpeg
def test_catalogus_heeft_24_looks_met_een_bestaande_lut(lookproject):
    uit = _vraag("project.looks", project="look")
    alle = uit["looks"]
    # 24 looks plus "origineel", de knop die niets doet.
    assert len(alle) == 25
    assert alle[0]["id"] == "origineel"
    assert uit["sferen"][0] == "Alles"

    sferen = {x["sfeer"] for x in alle if x["sfeer"]}
    assert sferen == set(uit["sferen"][1:])

    for x in alle[1:]:
        assert looks.lut_pad(x["id"]) is not None, f"{x['id']} heeft geen .cube"
        # Naar buiten toe is alles 0..1; `looks.json` houdt 0..100 binnenshuis.
        assert all(0.0 <= v <= 1.0 for v in x["afwerking"].values()), x
    # `origineel` krijgt bewust geen LUT: dan kan hij ook niets veranderen.
    assert looks.lut_pad("origineel") is None


@nodig_ffmpeg
def test_look_zetten_komt_terug_en_een_onbekende_look_wordt_geweigerd(lookproject):
    _vraag("project.look.zet", project="look", id=LOOK, sterkte=STERKTE,
           afwerking={**AFWERKING, "onzin": 3})
    gekozen = _vraag("project.looks", project="look")["gekozen"]
    assert gekozen["id"] == LOOK
    assert gekozen["sterkte"] == pytest.approx(STERKTE)
    assert gekozen["afwerking"]["vignet"] == pytest.approx(0.35)
    # Een onbekend veld hoort weggegooid, niet doorgegeven: `Afwerking(**d)`
    # zou er anders op klappen en de montage kosten.
    assert "onzin" not in gekozen["afwerking"]
    assert gekozen["afwerking"]["breedbeeld"] == 0.0

    with pytest.raises(ValueError):
        looks.zet("look", "bestaatniet", 1.0, {})

    # Buiten 0..1 gaat tegen de grens aan in plaats van door te lekken.
    looks.zet("look", LOOK, 9.0, {"korrel": -2})
    terug = looks.keuze("look")
    assert terug["sterkte"] == 1.0 and terug["afwerking"]["korrel"] == 0.0
    looks.zet("look", LOOK, STERKTE, AFWERKING)


# -- render ----------------------------------------------------------------


@nodig_ffmpeg
def test_render_met_look_houdt_het_frameaantal_en_verandert_de_kleur(lookproject):
    """De twee dingen die tegelijk waar moeten zijn.

    De kleur mag veranderen, het ritme niet. Een filterketen die een frame
    laat vallen schuift alles erna van de beat af — dat is de duurste fout in
    dit project en daarom staat hij in elke rendertest.
    """
    project, pdir, _ = lookproject

    kaal = _edl(project, Look(id="geen"), Afwerking())
    kaal.schrijf(pdir / "edl.json")
    zonder = render_mod.render(project, opties=render_mod.RenderOpties(modus="preview"),
                               log=lambda *_: None)
    zonder = zonder.rename(zonder.with_name("zonder-look.mp4"))

    met = _edl(project, Look(id=LOOK, sterkte=STERKTE), Afwerking(**AFWERKING))
    met.schrijf(pdir / "edl.json")
    uit = render_mod.render(project, opties=render_mod.RenderOpties(modus="preview"),
                            log=lambda *_: None)

    assert _frames(uit) == BLOK_FRAMES, "de look mag geen frame kosten"
    assert _frames(zonder) == BLOK_FRAMES

    verschil = _rgb(uit).mean(axis=(0, 1)) - _rgb(zonder).mean(axis=(0, 1))
    print(f"\nlook {LOOK}@{STERKTE}: ΔRGB {np.round(verschil, 2)}")
    assert np.abs(verschil).max() > 2.0, f"de look is niet te zien: {verschil}"


@nodig_ffmpeg
def test_het_voorbeeld_komt_de_tweede_keer_uit_de_cache(lookproject):
    """Dezelfde vraag levert hetzelfde bestand, een andere vraag een nieuw.

    Zonder die tweede helft zou de cache een verkeerde kleur teruggeven zodra
    de gebruiker aan de sterkteschuif draait. De kleurvergelijking zelf staat
    in `test_gouden_frames.py` — zes beelden × zes looks, PLAN-v2 §4.4.
    """
    project, pdir, _ = lookproject
    _edl(project, Look(id=LOOK, sterkte=STERKTE), Afwerking(**AFWERKING)).schrijf(
        pdir / "edl.json"
    )

    uit = looks.voorbeeld(project, LOOK, STERKTE, AFWERKING, breedte=0)
    assert uit["uit_cache"] is False
    assert Path(uit["pad"]).suffix == ".png", "een JPG kost 0,74 ΔE2000 voor niets"

    opnieuw = looks.voorbeeld(project, LOOK, STERKTE, AFWERKING, breedte=0)
    assert opnieuw["uit_cache"] is True
    assert opnieuw["pad"] == uit["pad"]

    ander = _vraag("project.look.voorbeeld", project=project, id=LOOK,
                   sterkte=0.4, afwerking=AFWERKING, breedte=160)
    assert ander["pad"] != uit["pad"]
    assert Path(ander["pad"]).exists()


@nodig_ffmpeg
def test_de_keuze_overleeft_een_nieuwe_montage(lookproject):
    """`maak_video()` schrijft een verse EDL; de look moet er daarna nog in staan."""
    project, pdir, _ = lookproject
    looks.zet(project, LOOK, STERKTE, AFWERKING)

    # Niet de hele montage draaien — dat kost een minuut en meet iets anders.
    # Dit is precies de stap die `montage.maak_video()` erbij doet.
    vers = _edl(project, Look(), Afwerking())
    looks.pas_toe(vers, looks.keuze(project))
    vers.schrijf(pdir / "edl.json")

    terug = json.loads((pdir / "edl.json").read_text(encoding="utf-8"))
    assert terug["look"] == {"id": LOOK, "sterkte": STERKTE}
    assert terug["afwerking"]["vignet"] == pytest.approx(0.35)


# --------------------------------------------------------------------------
# Paden in een filterketen, en wat sterkte betekent
# --------------------------------------------------------------------------

# Een LUT van 2x2x2 die alles pal rood maakt. Overdreven met opzet: zo is aan
# de gemiddelde kleur meteen te zien hoeveel look er doorkomt.
ROOD_CUBE = "LUT_3D_SIZE 2\n" + "\n".join(["1.0 0.0 0.0"] * 8) + "\n"
GRIJS = 128  # waar `color=gray` in rgb24 op uitkomt


def _gemiddelde_kleur(filtertekst: str) -> tuple[float, float, float]:
    """Eén frame van een grijs vlak door `filtertekst`, als (r, g, b)."""
    r = subprocess.run(
        [
            str(paths.ffmpeg()), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=64x48:rate=1:duration=1",
            "-vf", filtertekst, "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        capture_output=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    beeld = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 3).astype(float)
    return tuple(beeld.mean(axis=0))


def test_ffmpeg_pad_escapeert_voor_beide_parserlagen():
    """Een pad moet er twee keer langs: eerst de optieparser van het filter
    (die knipt op `:`), daarna de ketenparser (die knipt op `,` `;` `[` `]`).

    Een Windows-schijfletter struikelde over de eerste laag, een apostrof en
    een komma over de tweede.
    """
    assert render_mod._ffmpeg_pad(Path("C:/looks/noir.cube")) == "C\\\\:/looks/noir.cube"
    assert render_mod._ffmpeg_pad(Path("/a/O'Neil/n.cube")) == "/a/O\\\\\\'Neil/n.cube"
    assert render_mod._ffmpeg_pad(Path("/a/Film, 2/n.cube")) == "/a/Film\\, 2/n.cube"
    # Niet-ASCII is gewoon tekst; daar hoort geen backslash bij.
    assert render_mod._ffmpeg_pad(Path("/a/José/n.cube")) == "/a/José/n.cube"


@nodig_ffmpeg
def test_lut_uit_een_lastig_pad_draait_echt(tmp_path):
    """Met de meegeleverde ffmpeg: dubbele punt, spatie, apostrof, komma en
    niet-ASCII in één pad mogen de render niet breken.

    De map heet letterlijk `C:` — dat mag op macOS en bewijst precies de
    schijfletter waar het op Windows op stuk liep.
    """
    map_ = tmp_path / "C:" / "Users" / "José O'Neil" / "Film, deel 2"
    map_.mkdir(parents=True)
    lut = map_ / "noir.cube"
    lut.write_text(ROOD_CUBE, encoding="utf-8")

    kleur = _gemiddelde_kleur(f"lut3d=file={render_mod._ffmpeg_pad(lut)}:interp=tetrahedral")
    assert kleur[0] > 200 and kleur[1] < 60, kleur


@nodig_ffmpeg
@pytest.mark.parametrize("sterkte", [0.0, 0.25, 0.5, 0.85, 1.0])
def test_sterkte_loopt_van_origineel_naar_volle_look(tmp_path, monkeypatch, sterkte):
    """Sterkte 1,0 is de volle look, 0,0 het origineel, 0,5 er tussenin.

    Stond omgekeerd: ffmpeg weegt `all_opacity` bij modus `normal` naar de
    BOVENSTE laag (dst = boven*o + onder*(1-o)), terwijl elke andere modus
    het naar het resultaat van de blend weegt. De LUT stond onderaan, dus
    sterkte 1,00 gaf het origineel en 0,00 de volle look. Precies op 0,50
    valt dat niet op — die mengverhouding is symmetrisch — vandaar ook 0,25
    en 0,85 (de standaardsterkte uit `looks.json`).

    Expliciet met `BEATCUT_COMPOSITOR=0`: sinds 03-10-2026 doet de native
    compositor de look en geeft `_lookfilter` een lege keten terug. Deze test
    gaat juist over de ffmpeg-terugval, dus die moet hier aan staan.
    """
    monkeypatch.setenv("BEATCUT_COMPOSITOR", "0")
    lut = tmp_path / "rood.cube"
    lut.write_text(ROOD_CUBE, encoding="utf-8")
    monkeypatch.setattr(looks, "lut_pad", lambda look_id: lut)

    filtertekst = render_mod._lookfilter(
        Look(id="rood", sterkte=sterkte), Afwerking(), Canvas(64, 48, 30)
    )
    if sterkte == 0.0:
        assert filtertekst == ""  # geen look, geen filter
        return

    r, g, b = _gemiddelde_kleur(filtertekst)
    verwacht_r = GRIJS + (255 - GRIJS) * sterkte
    verwacht_g = GRIJS * (1 - sterkte)
    assert abs(r - verwacht_r) < 8, (r, g, b)
    assert abs(g - verwacht_g) < 8, (r, g, b)
    assert abs(b - verwacht_g) < 8, (r, g, b)
