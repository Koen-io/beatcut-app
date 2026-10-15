#!/usr/bin/env bash
# Eén editie bouwen: Vite én Tauri op dezelfde editie zetten.
#
#     app/edities/bouw.sh p-alv                    # app + dmg (macOS) / nsis (Windows)
#     app/edities/bouw.sh p-alv --bundles app      # alleen de .app, sneller
#     app/edities/bouw.sh beatcut
#
# Extra argumenten gaan door naar `tauri build`.
set -euo pipefail
cd "$(dirname "$0")/.."

EDITIE="${1:-}"
[ -n "$EDITIE" ] || { echo "gebruik: edities/bouw.sh <editie> [tauri build-opties]" >&2; exit 2; }
[ -f "edities/$EDITIE/editie.json" ] || { echo "onbekende editie: $EDITIE" >&2; exit 2; }
shift

CONFIG=()
if [ "$EDITIE" != "beatcut" ]; then
  [ -f "edities/$EDITIE/tauri.conf.json" ] || { echo "edities/$EDITIE/tauri.conf.json ontbreekt" >&2; exit 2; }
  CONFIG=(--config "edities/$EDITIE/tauri.conf.json")
fi

export BEATCUT_EDITIE="$EDITIE"

# Het updatetoken van een editie met een privé-releases-repo komt uit de
# sleutelhanger (installer/palv-token.sh). Zonder token bouwt de app wel,
# maar kan hij zichzelf niet bijwerken — bouw.sh zegt dat dan hardop.
if [ "$EDITIE" = "p-alv" ] && [ -z "${BEATCUT_UPDATE_TOKEN:-}" ]; then
  if BEATCUT_UPDATE_TOKEN="$(security find-generic-password -s palv-releases-token -a koen -w 2>/dev/null)"; then
    export BEATCUT_UPDATE_TOKEN
    echo "bouw.sh: updatetoken uit de sleutelhanger ingebakken"
  else
    echo "bouw.sh: LET OP — geen updatetoken (installer/palv-token.sh); deze build kan zichzelf niet bijwerken" >&2
  fi
fi

# De updater-handtekening: `createUpdaterArtifacts` staat aan, dus zonder
# sleutel weigert `tauri build` ná het bundelen. De sleutel staat op Koens
# Mac buiten de repo (installer/LEESMIJ.md § "De sleutel").
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -f "$HOME/.tauri/beatcut-updater.key" ]; then
  TAURI_SIGNING_PRIVATE_KEY="$(cat "$HOME/.tauri/beatcut-updater.key")"
  export TAURI_SIGNING_PRIVATE_KEY
  if [ -z "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" ]; then
    TAURI_SIGNING_PRIVATE_KEY_PASSWORD="$(security find-generic-password -s beatcut-updater -a koen -w 2>/dev/null || true)"
    export TAURI_SIGNING_PRIVATE_KEY_PASSWORD
  fi
  echo "bouw.sh: updater-sleutel uit ~/.tauri"
fi

exec npm run tauri -- build "${CONFIG[@]}" "$@"
