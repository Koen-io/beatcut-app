"""Nep-ACE-Step: spreekt hetzelfde protocol, zonder 11 GB model.

Maakt een kliktrack van de gevraagde duur waarvan de laatste 20 % stilte is -
precies de fout die het echte model maakt (`vendor/ace-step/VERSLAG.md` §4).
Daarmee is de trim-stap van `muziekgen.nabewerk()` echt te toetsen.

Draait met de Python van BeatCut zelf; `muziekgen.Server._commando()` pakt dit
script op via `BEATCUT_MUZIEKSERVER`.
"""

import json
import os
import sys

import numpy as np
import soundfile as sf

SR = 48000
STILTE_FRACTIE = 0.2


def uit(d):
    sys.stdout.write(json.dumps(d) + "\n")
    sys.stdout.flush()


def maak(pad, duur, bpm, seed):
    rng = np.random.default_rng(seed)
    muziek = duur * (1.0 - STILTE_FRACTIE)
    t = np.arange(int(SR * duur)) / SR
    tik = 60.0 / bpm
    kick = 0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-9 * np.mod(t, tik))
    toon = 0.2 * np.sin(2 * np.pi * (440 + rng.integers(0, 40)) * t)
    y = (kick + toon).astype(np.float32)
    y[t >= muziek] = 0.0
    y = y / max(1e-6, float(np.abs(y).max())) * 0.89  # zoals ACE-Step: piek op -1 dB
    sf.write(pad, np.stack([y, y], axis=1), SR, subtype="PCM_16")


uit({"gereed": True, "model": "nepmuziekserver"})

for n, regel in enumerate(sys.stdin):
    regel = regel.strip()
    if not regel:
        continue
    v = json.loads(regel)
    if v.get("opdracht") == "stop":
        break
    pad = os.path.join(v["map"], f"nep-{n}-{v['seed']}.wav")
    maak(pad, float(v["duur"]), int(v["bpm"]), int(v["seed"]))
    uit({"ok": True, "pad": pad})
