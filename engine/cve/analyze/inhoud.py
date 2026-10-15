"""Inhoud - wát er in beeld staat. De haak voor een beeldmodel.

`hoogtepunten.py` meet *dat* er iets gebeurt; dit bestand is de plek voor
*wat* er te zien is: een strand, een gezicht van dichtbij, een drone boven
een dorp. Dat vraagt een beeldmodel (CLIP/SigLIP-achtig) dat per segment een
embedding maakt. Zo'n model is honderden MB en hoort, net als het
muziekmodel, door de app opgehaald te worden - niet in git, niet verplicht
(regel 5: de werk-editie draait offline, ook zonder dit model).

Stand 13-10-2026: alleen de interface en de nul-implementatie. De regisseur
en de segmentatie werken er al mee (`embedding` per segment, `None` zonder
model); een echte implementatie hoeft alleen `Inhoudsmodel` te vullen en in
`kies_model()` gekozen te worden. Kandidaat: een ONNX-export van CLIP
ViT-B/32 via onnxruntime (cross-platform, ~90 MB gequantiseerd), met de
tekst-embeddings van een vaste lijst labels vooraf uitgerekend en meegeleverd,
zodat er geen tokenizer en geen tekstmodel op de machine van de gebruiker
hoeven te draaien.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Inhoud:
    """Wat een model over één segment zegt. Leeg = geen model."""

    embedding: list[float] | None = None
    # Labels met zekerheid 0..1, bijvoorbeeld {"strand": 0.8, "mensen": 0.3}.
    labels: dict[str, float] = field(default_factory=dict)


class Inhoudsmodel:
    """Basisinterface. `beschikbaar()` zegt of het model er op deze computer is."""

    naam = "geen"

    def beschikbaar(self) -> bool:
        return False

    def bekijk(self, beeld_pad: str) -> Inhoud:
        """Eén beeld (JPG van het midden van een segment) → Inhoud."""
        return Inhoud()


class GeenModel(Inhoudsmodel):
    """Zonder model: elk segment is onbekend, en dat is geen fout."""


def kies_model() -> Inhoudsmodel:
    """Het model dat hier beschikbaar is; nu altijd `GeenModel`."""
    return GeenModel()


def gelijkenis(a: list[float] | None, b: list[float] | None) -> float | None:
    """Cosinusgelijkenis 0..1 tussen twee embeddings, of None zonder embeddings.

    Voor de regisseur: twee shots die hetzelfde *tonen* (niet alleen dezelfde
    pixels, waar dHash op kijkt) mogen niet naast elkaar staan.
    """
    if not a or not b or len(a) != len(b):
        return None
    import math

    inp = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return max(0.0, min(1.0, (inp / (na * nb) + 1.0) / 2.0))
