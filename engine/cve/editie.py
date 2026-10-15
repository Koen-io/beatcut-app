"""De naam waaronder de engine draait.

BeatCut is de standaard. Een andere editie van dezelfde app — zoals de
P-ALV Movie Maker — zet `BEATCUT_APPNAAM` in de omgeving van de engine
(`app/src-tauri/src/lib.rs` doet dat uit `productName` in de Tauri-config),
en dan heet alles wat de gebruiker ziet of in zijn mappen terugvindt naar
die editie: de steunmap, de Films-map, de meldingen.

Regel 6 van CLAUDE.md geldt hier ook: in de code staat geen merknaam, alleen
deze ene plek die hem uit de omgeving leest. Alles wat een naam toont, haalt
hem hier vandaan.
"""

from __future__ import annotations

import os

#: Zichtbare naam van de app ("BeatCut", "P-ALV Movie Maker").
NAAM: str = os.environ.get("BEATCUT_APPNAAM", "BeatCut").strip() or "BeatCut"

#: Mapnaam zonder tekens die op Windows of in een shell lastig zijn.
MAPNAAM: str = NAAM.replace("/", "-").replace("\\", "-").replace(":", "-")


def is_beatcut() -> bool:
    return NAAM == "BeatCut"
