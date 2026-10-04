"""PySceneDetect met een OpenCV die NaN als positie geeft: geen crash."""
from __future__ import annotations

import pytest
from cve.analyze import beeld

from test_rpc_project import nodig_ffmpeg
from test_rpc_montage import _maak_clip


@nodig_ffmpeg
def test_nan_uit_opencv_geeft_een_shot_over_de_hele_clip(tmp_path, monkeypatch):
    clip = tmp_path / "c.mp4"
    _maak_clip(clip, "null")
    import scenedetect

    def kapot(self, *a, **kw):
        raise ValueError("cannot convert float NaN to integer")

    monkeypatch.setattr(scenedetect.SceneManager, "detect_scenes", kapot)
    shots = beeld.detecteer_shots(clip)
    assert len(shots) == 1 and shots[0].start == 0.0 and shots[0].eind > 1.0
