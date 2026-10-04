"""Contactvellen: veel beeld in weinig tokens.

Een model dat naar je video moet kijken, kan dat niet frame voor frame. Een
montage van tachtig seconden is 2400 beelden; los opgestuurd is dat miljoenen
tokens en een rekening waar niemand blij van wordt.

Een contactvel lost dat op: zestien momenten in één afbeelding, met een
nummer in de hoek zodat het model kan zeggen wélk beeld het bedoelt. Zo kost
een heel hoofdstuk ongeveer evenveel als één foto.

Meting op dit project: 100 losse shots ≈ 150 k tokens, dezelfde 100 als
contactvellen ≈ 10 k. Dat is de reden dat dit bestand bestaat.

Puur mechanisch — hier komt geen model aan te pas. Dit maakt alleen het
plaatje dat een model straks bekijkt.
"""

from __future__ import annotations

import math
from pathlib import Path

TEGELS = 16          # 4x4; meer past niet leesbaar in één afbeelding
TEGEL_BREEDTE = 320  # per tegel; 4x4 geeft 1280 px breed


def _grijp(pad: Path, tijden: list[float], breedte: int):
    """Haal een handvol frames uit een videobestand.

    Met opencv en niet met ffmpeg: we hebben de frames toch in het geheugen
    nodig om ze aan elkaar te plakken, en zo blijft het één proces.
    """
    import cv2

    cap = cv2.VideoCapture(str(pad))
    if not cap.isOpened():
        return []
    uit = []
    for t in tijden:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, beeld = cap.read()
        if not ok:
            continue
        h, b = beeld.shape[:2]
        hoogte = max(1, int(round(breedte * h / b)))
        uit.append(cv2.resize(beeld, (breedte, hoogte), interpolation=cv2.INTER_AREA))
    cap.release()
    return uit


def maak(
    momenten: list[tuple[Path, float]],
    doel: Path,
    *,
    breedte: int = TEGEL_BREEDTE,
) -> Path | None:
    """Zet de opgegeven momenten in één afbeelding met een raster.

    `momenten` is een lijst van (bestand, seconde). Bestanden worden
    gegroepeerd zodat elke clip maar één keer geopend hoeft te worden -
    op 4K-materiaal scheelt dat seconden per vel.
    """
    import cv2
    import numpy as np

    if not momenten:
        return None
    momenten = momenten[:TEGELS]

    # Per bestand bij elkaar zoeken, maar de oorspronkelijke volgorde
    # onthouden: het nummer in de hoek moet kloppen met wat wij bedoelen.
    per_bestand: dict[Path, list[tuple[int, float]]] = {}
    for i, (pad, t) in enumerate(momenten):
        per_bestand.setdefault(pad, []).append((i, t))

    beelden: dict[int, "np.ndarray"] = {}
    for pad, lijst in per_bestand.items():
        frames = _grijp(pad, [t for _, t in lijst], breedte)
        for (i, _), beeld in zip(lijst, frames):
            beelden[i] = beeld
    if not beelden:
        return None

    kolommen = min(4, len(momenten))
    rijen = math.ceil(len(momenten) / kolommen)
    hoogte = max(b.shape[0] for b in beelden.values())
    vel = np.zeros((rijen * hoogte, kolommen * breedte, 3), dtype=np.uint8)

    for i in range(len(momenten)):
        beeld = beelden.get(i)
        if beeld is None:
            continue
        r, k = divmod(i, kolommen)
        y, x = r * hoogte, k * breedte
        vel[y : y + beeld.shape[0], x : x + breedte] = beeld

        # Nummer linksboven, met een donker blokje eronder zodat het ook op
        # een lichte lucht leesbaar blijft.
        etiket = str(i + 1)
        cv2.rectangle(vel, (x + 6, y + 6), (x + 44, y + 34), (0, 0, 0), -1)
        cv2.putText(vel, etiket, (x + 14, y + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    doel.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(doel), vel, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return doel


def uit_hoofdstuk(
    blokken: list[dict],
    bronmap: Path,
    proxymap: Path,
    doel: Path,
    *,
    aantal: int = TEGELS,
) -> Path | None:
    """Een contactvel van één hoofdstuk uit de montage.

    Neemt momenten gelijkmatig verdeeld over de blokken, uit de proxies -
    die zijn klein en openen in een fractie van de tijd die een 4K-bestand
    kost, en voor "wat is hier te zien" is 540p ruim genoeg.
    """
    if not blokken:
        return None
    momenten: list[tuple[Path, float]] = []
    per_blok = max(1, aantal // max(1, len(blokken)))
    for b in blokken:
        bron = proxymap / f"{b.get('clip', '')}.mp4"
        if not bron.exists():
            bron = bronmap / b.get("bestand", "")
        if not bron.exists():
            continue
        start = float(b.get("bron_start", 0))
        duur = float(b.get("duur", 0))
        for n in range(per_blok):
            deel = (n + 0.5) / per_blok
            momenten.append((bron, start + duur * deel))
    return maak(momenten[:aantal], doel)
