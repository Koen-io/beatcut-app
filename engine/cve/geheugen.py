"""Fase 8 - stijl-geheugen.

Elke keer dat je een shot vervangt, weggooit of vastzet, doe je een uitspraak
over je smaak. Die uitspraken zijn gratis informatie: ze staan al in de
interface, ze kosten je geen extra handeling, en ze zijn veel preciezer dan
een gewicht dat je met de hand zou bijstellen.

Hoe het werkt, in één alinea: elk segment heeft een profiel van signalen
(beweging, scherpte, shake, ...) tussen 0 en 1. Vervang je shot A door shot B,
dan is het verschil B − A per signaal precies de richting van je voorkeur.
Genoeg van die verschillen bij elkaar en je weet welk signaal je zwaarder
weegt dan de stijl aannam.

Drie ontwerpkeuzes die ertoe doen:

**Het geleerde staat los van `styles/<naam>.md`.** Dat bestand is met de hand
geschreven en moet leesbaar blijven. De bijstelling gaat naar
`styles/geleerd/<naam>.json`. Zo zie je altijd wat jij zei en wat de engine
erbij bedacht, en `cve stijl <naam> --vergeet` maakt het in één klap ongedaan.

**Er is een ondergrens aan bewijs.** Onder `MIN_KEUZES` waarnemingen gebeurt
er niets. Eén vervanging kan toeval zijn; vijf in dezelfde richting niet.

**En een bovengrens aan de uitslag.** Een gewicht mag met hoogstens
`MAX_BIJSTELLING` verschuiven. Zonder die rem draait een montage na twintig
keuzes helemaal om een enkel signaal, en dat is geen smaak meer maar een
uitschieter die zichzelf versterkt.

Wat het bewust *niet* doet: een keuze die je met ⌘Z terugdraait blijft staan.
Je hebt hem gemaakt, en dat zegt iets - ook als je hem daarna liever anders
zag. Wie dat wil corrigeren gebruikt `cve stijl <naam> --vergeet`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import paths

# Onder dit aantal waarnemingen per signaal stellen we niets bij.
MIN_KEUZES = 4
# Hoeveel van het gemeten verschil we overnemen. Laag gehouden: het gaat om
# een duwtje per video, niet om een koerswijziging.
LEERSNELHEID = 0.30
# Hoever een gewicht ooit mag verschuiven ten opzichte van het stijlbestand.
MAX_BIJSTELLING = 0.10
# Verschillen kleiner dan dit zijn ruis, geen voorkeur.
RUISGRENS = 0.02

SOORTEN = ("vervangen", "verwijderd", "vastgezet")


def keuzes_pad(project: str) -> Path:
    return paths.project_dir(project) / "keuzes.json"


def geleerd_pad(stijl: str) -> Path:
    return paths.STYLES / "geleerd" / f"{stijl}.json"


# --------------------------------------------------------------------------
# Opzoeken waar een shot vandaan komt
# --------------------------------------------------------------------------


def _segment_bij(analyse: dict, clip: str, bron_start: float, duur: float) -> dict | None:
    """Zoek het segment waar dit stuk bronmateriaal in valt.

    Niet op gelijkheid zoeken: de regisseur snijdt een segment op de
    rasterlengte en centreert dat, dus `bron_start` ligt zelden precies op
    `segment.start`. Het midden van het shot valt wel altijd binnen het
    segment waar het uit komt.
    """
    midden = bron_start + duur / 2.0
    besten = [
        s for s in analyse.get("segmenten", [])
        if s.get("clip") == clip and s["start"] <= midden <= s["eind"]
    ]
    if besten:
        return max(besten, key=lambda s: s.get("score", 0.0))
    # Valt het buiten alle segmenten, neem dan het dichtstbijzijnde van
    # dezelfde clip. Beter een profiel dat er net naast zit dan geen.
    van_clip = [s for s in analyse.get("segmenten", []) if s.get("clip") == clip]
    if not van_clip:
        return None
    return min(van_clip, key=lambda s: abs((s["start"] + s["eind"]) / 2 - midden))


def _profiel(segment: dict | None) -> dict[str, float]:
    if not segment:
        return {}
    return {k: float(v) for k, v in (segment.get("onderdelen") or {}).items()}


def _gemiddeld_profiel(edl_video: list[dict], analyse: dict, overslaan: int | None = None) -> dict[str, float]:
    """Het gemiddelde profiel van de montage zoals die er nu staat.

    Dat is de maatstaf waartegen een verwijderd of vastgezet shot afgezet
    wordt: niet "is dit shot goed", maar "wijkt het af van de rest, en welke
    kant op".
    """
    opgeteld: dict[str, list[float]] = {}
    for i, b in enumerate(edl_video):
        if overslaan is not None and i == overslaan:
            continue
        p = _profiel(_segment_bij(analyse, b.get("clip", ""), float(b.get("bron_start", 0)), float(b.get("duur", 0))))
        for k, v in p.items():
            opgeteld.setdefault(k, []).append(v)
    return {k: sum(v) / len(v) for k, v in opgeteld.items() if v}


# --------------------------------------------------------------------------
# Vastleggen
# --------------------------------------------------------------------------


def noteer(
    project: str,
    soort: str,
    *,
    stijl: str,
    weg: dict | None = None,
    komt: dict | None = None,
    houd: dict | None = None,
    index: int | None = None,
) -> dict:
    """Leg één keuze vast en werk het geleerde van deze stijl bij.

    `weg`, `komt` en `houd` zijn elk `{clip, bron_start, duur}`:

        vervangen    weg = het oude shot, komt = het nieuwe
        verwijderd   weg = het weggegooide shot
        vastgezet    houd = het shot dat moet blijven staan

    De profielen worden hier opgezocht en meteen meegeschreven, zodat een
    keuze leesbaar blijft ook als `analysis.json` later opnieuw gemaakt wordt.
    """
    if soort not in SOORTEN:
        raise ValueError(f"onbekende soort keuze: {soort}")

    pdir = paths.project_dir(project)
    analyse_pad = pdir / "analysis.json"
    if not analyse_pad.exists():
        raise FileNotFoundError("geen analysis.json; keuze niet te duiden")
    analyse = json.loads(analyse_pad.read_text(encoding="utf-8"))

    def prof(d: dict | None) -> dict[str, float]:
        if not d:
            return {}
        return _profiel(
            _segment_bij(analyse, d.get("clip", ""), float(d.get("bron_start", 0)), float(d.get("duur", 0)))
        )

    edl_pad = pdir / "edl.json"
    edl_video = []
    if edl_pad.exists():
        edl_video = json.loads(edl_pad.read_text(encoding="utf-8")).get("video", [])

    keuze = {
        "wanneer": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": project,
        "stijl": stijl,
        "soort": soort,
        "weg": {**(weg or {}), "profiel": prof(weg)},
        "komt": {**(komt or {}), "profiel": prof(komt)},
        "houd": {**(houd or {}), "profiel": prof(houd)},
        "gemiddeld": _gemiddeld_profiel(edl_video, analyse, overslaan=index),
    }

    pad = keuzes_pad(project)
    alle = []
    if pad.exists():
        try:
            alle = json.loads(pad.read_text(encoding="utf-8")).get("keuzes", [])
        except json.JSONDecodeError:
            alle = []
    alle.append(keuze)
    pad.write_text(
        json.dumps({"versie": 1, "keuzes": alle}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )

    return leer(stijl)


# --------------------------------------------------------------------------
# Leren
# --------------------------------------------------------------------------


def _verschillen(keuze: dict) -> dict[str, float]:
    """Wat zegt deze ene keuze over de voorkeur, per signaal.

    Positief betekent: meer van dit signaal graag. Dat werkt voor signalen met
    een negatief gewicht net zo goed - kiest iemand consequent het rustigere
    shot, dan is het verschil in `shake` negatief en zakt dat gewicht verder
    onder nul. Eén regel, geen uitzonderingen.
    """
    weg = (keuze.get("weg") or {}).get("profiel") or {}
    komt = (keuze.get("komt") or {}).get("profiel") or {}
    houd = (keuze.get("houd") or {}).get("profiel") or {}
    gem = keuze.get("gemiddeld") or {}

    if keuze["soort"] == "vervangen" and weg and komt:
        basis, doel = weg, komt
    elif keuze["soort"] == "verwijderd" and weg and gem:
        # Weggegooid shot afgezet tegen de rest van de montage: de montage is
        # wat blijft staan, dus die kant op.
        basis, doel = weg, gem
    elif keuze["soort"] == "vastgezet" and houd and gem:
        # Vastgezet is het omgekeerde: dít shot moet blijven, meer hiervan.
        basis, doel = gem, houd
    else:
        return {}

    sleutels = set(basis) & set(doel)
    return {k: doel[k] - basis[k] for k in sleutels}


def _alle_keuzes(stijl: str) -> list[dict]:
    uit = []
    if not paths.PROJECTEN.exists():
        return uit
    for pad in sorted(paths.PROJECTEN.glob("*/keuzes.json")):
        try:
            data = json.loads(pad.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        uit += [k for k in data.get("keuzes", []) if k.get("stijl") == stijl]
    return uit


def leer(stijl: str) -> dict:
    """Reken alle keuzes van deze stijl om naar een bijstelling per signaal."""
    keuzes = _alle_keuzes(stijl)

    verzameld: dict[str, list[float]] = {}
    for k in keuzes:
        for signaal, d in _verschillen(k).items():
            verzameld.setdefault(signaal, []).append(d)

    bijstelling: dict[str, float] = {}
    bewijs: dict[str, int] = {}
    for signaal, waarden in sorted(verzameld.items()):
        bewijs[signaal] = len(waarden)
        if len(waarden) < MIN_KEUZES:
            continue
        gemiddeld = sum(waarden) / len(waarden)
        if abs(gemiddeld) < RUISGRENS:
            continue
        d = LEERSNELHEID * gemiddeld
        bijstelling[signaal] = round(max(-MAX_BIJSTELLING, min(MAX_BIJSTELLING, d)), 4)

    geleerd = {
        "versie": 1,
        "stijl": stijl,
        "bijgewerkt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keuzes": len(keuzes),
        "bewijs": bewijs,
        "bijstelling": bijstelling,
    }

    pad = geleerd_pad(stijl)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(geleerd, indent=1, ensure_ascii=False), encoding="utf-8")
    return geleerd


def laad_geleerd(stijl: str) -> dict:
    pad = geleerd_pad(stijl)
    if not pad.exists():
        return {"stijl": stijl, "keuzes": 0, "bewijs": {}, "bijstelling": {}}
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"stijl": stijl, "keuzes": 0, "bewijs": {}, "bijstelling": {}}


def vergeet(stijl: str) -> bool:
    """Gooi het geleerde weg. De keuzes zelf blijven staan.

    Met opzet: het geleerde is een afgeleide en moet altijd opnieuw te maken
    zijn. Wie de keuzes zelf kwijt wil, verwijdert `keuzes.json` uit de
    projectmap - dat is een bewustere handeling dan een vlag op een commando.
    """
    pad = geleerd_pad(stijl)
    if pad.exists():
        pad.unlink()
        return True
    return False
