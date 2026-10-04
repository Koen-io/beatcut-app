#!/usr/bin/env bash
# ACE-Step 1.5 ophalen voor BeatCut — ongeveer 11 GB.
#
# Doel: ~/Library/Application Support/BeatCut/muziekmodel
# Dat is waar `paths.muziekmodel()` als eerste kijkt, dus een geïnstalleerde
# app vindt het hierna zonder dat er iets ingesteld hoeft te worden.
#
# Drie stukken: de code op een vaste commit, een eigen venv met uv, en de
# modelgewichten (9,4 GB). Het script is herhaalbaar: wat er al staat blijft
# staan. Niets wordt ooit verwijderd — bij twijfel stopt hij en zegt wat er is.
#
# Gebruik:
#   installer/muziekmodel/installeer-mac.sh            # echt installeren
#   installer/muziekmodel/installeer-mac.sh --droog    # alleen vertellen
#   DOEL=/ergens/anders installer/muziekmodel/installeer-mac.sh
set -euo pipefail

# Vaste commit, geen `main`. Het verslag van 03-10-2026 is op déze code
# gemeten (vendor/ace-step/VERSLAG.md); een latere commit kan andere
# modelnamen of een andere API hebben en dan breekt muziekgen.py stil.
REPO="https://github.com/ace-step/ACE-Step-1.5.git"
COMMIT="ca1e85f"
PYTHON_VERSIE="3.12"          # hun pyproject eist >=3.11,<3.13
LM_MODEL="acestep-5Hz-lm-1.7B"
DOEL="${DOEL:-$HOME/Library/Application Support/BeatCut/muziekmodel}"
DROOG=0
[[ "${1:-}" == "--droog" ]] && DROOG=1

zeg() { printf '%s\n' "$*"; }
doe() {
  if (( DROOG )); then zeg "  zou doen: $*"; else "$@"; fi
}

zeg "ACE-Step 1.5 → $DOEL"
(( DROOG )) && zeg "(droge proef: er wordt niets gewijzigd)"

for cmd in git uv; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    zeg "FOUT: '$cmd' staat niet op PATH."
    [[ "$cmd" == "uv" ]] && zeg "  Installeer het met: brew install uv"
    exit 1
  fi
done

if [[ -d "$DOEL/.git" ]]; then
  zeg "Code staat er al; commit $COMMIT uitchecken."
  doe git -C "$DOEL" fetch --depth 1 origin "$COMMIT"
  doe git -C "$DOEL" checkout --detach FETCH_HEAD
elif [[ -e "$DOEL" ]]; then
  zeg "FOUT: $DOEL bestaat maar is geen git-clone. Niets aangeraakt."
  zeg "  Verplaats of verwijder die map zelf en draai dit opnieuw."
  exit 1
else
  zeg "Code klonen op commit ${COMMIT}…"
  doe mkdir -p "$(dirname "$DOEL")"
  doe git init --quiet "$DOEL"
  doe git -C "$DOEL" remote add origin "$REPO"
  doe git -C "$DOEL" fetch --depth 1 origin "$COMMIT"
  doe git -C "$DOEL" checkout --detach FETCH_HEAD
fi

# HF_HOME binnen de installatie: zo staat de downloadcache niet verspreid over
# ~/.cache en is de hele installatie met één map te verwijderen.
export HF_HOME="$DOEL/hf"

zeg "Python ${PYTHON_VERSIE} en de pakketten (torch, mlx) — enkele minuten…"
doe uv python install "$PYTHON_VERSIE"
if (( DROOG )); then
  zeg "  zou doen: (cd \"$DOEL\" && uv sync --python $PYTHON_VERSIE)"
else
  ( cd "$DOEL" && uv sync --python "$PYTHON_VERSIE" )
fi

zeg "Modelgewichten ophalen (9,4 GB)…"
# Hun eigen downloader, zodat de bestandsnamen kloppen met wat de handler
# verwacht. Het heet `ensure_main_model`, niet `ensure_model` - hier stond het
# fout en dat gaf een ImportError (gemeten 03-10-2026 door de stap echt te
# draaien). Die ene aanroep haalt het DiT-model, de vae, de tekst-encoder en
# het 1,7B-taalmodel samen op; `ensure_lm_model` blijft als vangnet staan en
# doet niets als het er al is. Beide geven `(gelukt, bericht)` terug in plaats
# van een uitzondering, dus zelf toetsen - anders meldt dit script "klaar" bij
# een lege checkpoints-map.
if (( DROOG )); then
  zeg "  zou doen: (cd \"$DOEL\" && .venv/bin/python -c '<ensure_main_model + ensure_lm_model>')"
else
  ( cd "$DOEL" && .venv/bin/python - <<PY
import os, sys
sys.path.insert(0, os.getcwd())
from pathlib import Path
from acestep.model_downloader import ensure_lm_model, ensure_main_model

CP = Path(os.getcwd()) / "checkpoints"
for naam, (gelukt, bericht) in (
    ("model", ensure_main_model(checkpoints_dir=CP)),
    ("taalmodel", ensure_lm_model("$LM_MODEL", checkpoints_dir=CP)),
):
    print(naam + ": " + str(bericht))
    if not gelukt:
        raise SystemExit(naam + " ophalen mislukte: " + str(bericht))
print("modellen staan klaar")
PY
  )
fi

if (( DROOG )); then
  zeg "Droge proef klaar. git en uv zijn aanwezig; de stappen hierboven zijn wat er zou gebeuren."
  exit 0
fi

zeg "Controle…"
"$DOEL/.venv/bin/python" -c "import torch; print('torch', torch.__version__, 'mps', torch.backends.mps.is_available())"
du -sh "$DOEL"
# Zelfde marker als muziekinstall.py: zonder telt de steunmap niet als compleet.
printf 'ACE-Step 1.5 compleet\n' > "$DOEL/.beatcut-gereed"
zeg "Klaar. BeatCut vindt dit vanaf nu zelf (paths.muziekmodel())."
