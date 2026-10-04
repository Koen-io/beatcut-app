"""De titels zoals de live voorvertoning ze nodig heeft.

De export rendert elke overlay met HyperFrames naar een transparante MOV en
legt die over het beeld (`graphics.render_overlay`). Dat duurt per titel een
browserrender en is dus niets voor een voorvertoning die moet meelopen met de
klok. De speler draait daarom dezelfde compositie *zelf*: hetzelfde sjabloon
(`brands/sjablonen/titel20.*`), dezelfde GSAP-tijdlijn, dezelfde variabelen —
alleen zet hij de tijdlijn op de klok in plaats van hem frame voor frame uit
te renderen.

Wat hier dus over de draad gaat is niet HTML maar precies wat de renderer als
`--variables` meegeeft. Het sjabloon zelf zit in de app-bundel; zo hoeft de
webview geen bestanden buiten de projectmap te lezen (het asset-protocol van
Tauri komt daar niet) en blijft er één bron voor render én voorvertoning.
"""

from __future__ import annotations

from typing import Any

from . import graphics, paths
from .edl import EDL

# Welke overlay-soorten de speler zelf kan tekenen. De andere sjablonen staan
# niet in de app-bundel; die komen pas in de render in beeld. Ze worden
# teruggemeld in `overgeslagen` in plaats van stil weggelaten — een titel die
# in de export wél verschijnt en in de voorvertoning niet, is erger dan een
# melding.
GETEKEND = ("titel20",)


def voor_speler(project: str) -> dict[str, Any]:
    """De overlays van dit project, met hun variabelen en de canvasmaat."""
    edlpad = paths.project_dir(project) / "edl.json"
    if not edlpad.exists():
        return {"breedte": 0, "hoogte": 0, "titels": [], "overgeslagen": []}
    edl = EDL.lees(edlpad)
    merk = graphics.laad_merk(edl.merk)

    titels = []
    overgeslagen = []
    for o in edl.overlay:
        if o.soort not in GETEKEND:
            overgeslagen.append({"id": o.id, "soort": o.soort})
            continue
        titels.append({
            "id": o.id,
            "soort": o.soort,
            "start": o.tijdlijn_start,
            "duur": o.duur,
            # Letterlijk wat `render_overlay` als `--variables` doorgeeft, dus
            # inclusief de merkkleuren en de `duur` waar de animatie op rekent.
            "variabelen": graphics._variabelen(o, merk),
        })
    return {
        "breedte": edl.canvas.breedte,
        "hoogte": edl.canvas.hoogte,
        "titels": titels,
        "overgeslagen": overgeslagen,
    }
