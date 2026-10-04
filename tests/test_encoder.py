"""De encoderkeuze: wat in `-encoders` staat moet ook echt werken."""
from __future__ import annotations

import pytest

from cve import media


@pytest.fixture(autouse=True)
def _vers():
    media.video_encoder.cache_clear()
    yield
    media.video_encoder.cache_clear()


def test_gekozen_encoder_levert_echt_frames():
    naam, opties = media.video_encoder()
    assert media._werkt(naam, opties), naam


def test_een_encoder_zonder_hardware_wordt_overgeslagen(monkeypatch):
    # Zoals een pc zonder NVIDIA of een VM: alles faalt behalve de noodgreep.
    monkeypatch.setattr(media, "_werkt", lambda naam, opties: naam == "mpeg4")
    assert media.video_encoder()[0] == "mpeg4"


def test_beatcut_encoder_forceert_er_een(monkeypatch):
    monkeypatch.setenv("BEATCUT_ENCODER", "geen-bestaande-encoder")
    assert media.video_encoder() == media._NOODUITGANG
