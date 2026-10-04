#!/usr/bin/env bash
#
# Bewijst dat de Tauri-updater van BeatCut werkt, zonder GitHub en zonder
# release. Draai hem vanuit de projectwortel:
#
#     installer/updatertest.sh
#
# Wat het doet:
#
# 1. bouwt de app op de huidige versie (0.3.0) — een debug-bundel met de
#    cargo-feature `testendpoint`, want alleen die kent de vlag `--updatetest`;
# 2. zet de versie tijdelijk een patch hoger (0.3.1) en bouwt opnieuw, nu mét
#    updater-artefact (`BeatCut.app.tar.gz` + `.sig`);
# 3. zet `latest.json` en dat artefact op een lokale HTTP-server;
# 4. laat de oude app de update vinden, ophalen en de handtekening controleren;
# 5. vervangt die handtekening door een geldige handtekening van een ándere
#    sleutel en toont dat dezelfde app hem dan weigert.
#
# Waarom http mag: de updater staat een endpoint zonder https alleen toe in een
# debug-build. Een release-build weigert het. De grens zit dus in het programma,
# niet in dit script.
#
# Er wordt niets geïnstalleerd en de versie in de repo blijft staan zoals hij was.
set -euo pipefail

cd "$(dirname "$0")/.."
WORTEL="$PWD"
CONF="app/src-tauri/tauri.conf.json"
BUNDEL="app/src-tauri/target/debug/bundle/macos"
POORT="${POORT:-8765}"

fout() { echo "updatertest: $*" >&2; exit 1; }
kop()  { echo; echo "=== $* ==="; }

[ "$(uname)" = "Darwin" ] || fout "dit script is voor macOS; op Windows is het pad naar de bundel anders"
[ -f "$HOME/.tauri/beatcut-updater.key" ] || fout "~/.tauri/beatcut-updater.key ontbreekt (zie installer/LEESMIJ.md)"
[ -d installer/uit/beatcut-engine ] || fout "de ingevroren engine ontbreekt; eerst pyinstaller installer/beatcut.spec"

export TAURI_SIGNING_PRIVATE_KEY="$HOME/.tauri/beatcut-updater.key"
TAURI_SIGNING_PRIVATE_KEY_PASSWORD="$(security find-generic-password -s beatcut-updater -a koen -w)"
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD

OUD_VERSIE="$(node -p "require('./$CONF').version")"
NIEUW_VERSIE="$(node -e 'const v=process.argv[1].split(".");v[2]=+v[2]+1;console.log(v.join("."))' "$OUD_VERSIE")"
# `pwd -P`: op macOS geeft mktemp een pad onder /var, en /var is een symlink
# naar /private/var. De updater weigert te starten als `current_exe()` door een
# symlink loopt ("found current_exe() that contains a symlink").
WERK="$(cd "$(mktemp -d)" && pwd -P)"
SERVER=""

opruimen() {
  if [ -n "$SERVER" ]; then
    kill "$SERVER" 2>/dev/null || true
    wait "$SERVER" 2>/dev/null || true   # anders print bash "Terminated: 15"
  fi
  # De versie altijd terugzetten, ook als er iets afbreekt.
  node -e '
    const fs = require("fs"), p = process.argv[1];
    const j = JSON.parse(fs.readFileSync(p, "utf8"));
    j.version = process.argv[2];
    fs.writeFileSync(p, JSON.stringify(j, null, 2) + "\n");
  ' "$WORTEL/$CONF" "$OUD_VERSIE"
  rm -rf "$WERK"
}
trap opruimen EXIT

zet_versie() {
  node -e '
    const fs = require("fs"), p = process.argv[1];
    const j = JSON.parse(fs.readFileSync(p, "utf8"));
    j.version = process.argv[2];
    fs.writeFileSync(p, JSON.stringify(j, null, 2) + "\n");
  ' "$CONF" "$1"
}

bouw() {
  ( cd app && npm run tauri -- build --debug --features testendpoint --bundles app ) \
    > "$WERK/bouw-$1.log" 2>&1 || { tail -30 "$WERK/bouw-$1.log" >&2; fout "bouwen van $1 mislukte"; }
}

# ---------------------------------------------------------------- 1. de oude app
kop "1. $OUD_VERSIE bouwen (de app die bijgewerkt moet worden)"
bouw "$OUD_VERSIE"
cp -R "$BUNDEL/BeatCut.app" "$WERK/BeatCut-$OUD_VERSIE.app"
OUD_APP="$WERK/BeatCut-$OUD_VERSIE.app/Contents/MacOS/beatcut"
echo "   $WERK/BeatCut-$OUD_VERSIE.app"

# --------------------------------------------------------------- 2. de nieuwe app
kop "2. $NIEUW_VERSIE bouwen (de update, met handtekening)"
zet_versie "$NIEUW_VERSIE"
bouw "$NIEUW_VERSIE"
zet_versie "$OUD_VERSIE"

mkdir -p "$WERK/web"
cp "$BUNDEL/BeatCut.app.tar.gz" "$WERK/web/BeatCut-$NIEUW_VERSIE.app.tar.gz"
ECHTE_SIG="$(cat "$BUNDEL/BeatCut.app.tar.gz.sig")"
echo "   bundel $(du -h "$WERK/web/BeatCut-$NIEUW_VERSIE.app.tar.gz" | cut -f1), handtekening $(printf '%s' "$ECHTE_SIG" | wc -c | tr -d ' ') tekens"

# Een geldige handtekening, maar van een andere sleutel. Dat is de scherpe test:
# niet een kapotte base64, maar iemand die zijn eigen sleutel gebruikt. Mét
# `--app-version`, want dat zit ook in de echte handtekening — zo is de sleutel
# het enige verschil en kan de updater hem niet om een andere reden weigeren.
#
# `env -u`: staan TAURI_SIGNING_PRIVATE_KEY of het wachtwoord in de omgeving,
# dan pakt de signer die en niet de valse sleutel, en faalt hij zonder uitleg.
kop "2b. een valse sleutel maken en dezelfde bundel ermee ondertekenen"
SCHOON=(env -u TAURI_SIGNING_PRIVATE_KEY -u TAURI_SIGNING_PRIVATE_KEY_PASSWORD -u TAURI_SIGNING_PRIVATE_KEY_PATH)
( cd app && "${SCHOON[@]}" npx tauri signer generate -w "$WERK/vals.key" --password "" --force ) \
  > "$WERK/vals.log" 2>&1 || { cat "$WERK/vals.log" >&2; fout "de valse sleutel kon niet gemaakt worden"; }
( cd app && "${SCHOON[@]}" npx tauri signer sign -f "$WERK/vals.key" -p "" \
    --app-version "$NIEUW_VERSIE" "$WERK/web/BeatCut-$NIEUW_VERSIE.app.tar.gz" ) \
  > "$WERK/vals-sign.log" 2>&1 || { cat "$WERK/vals-sign.log" >&2; fout "ondertekenen met de valse sleutel mislukte"; }
VALSE_SIG="$(cat "$WERK/web/BeatCut-$NIEUW_VERSIE.app.tar.gz.sig")"
rm -f "$WERK/web/BeatCut-$NIEUW_VERSIE.app.tar.gz.sig"
[ "$VALSE_SIG" != "$ECHTE_SIG" ] || fout "de valse handtekening is gelijk aan de echte — dat kan niet"

maak_latest() {  # handtekening -> latest.json
  BASIS="http://127.0.0.1:$POORT" V="$NIEUW_VERSIE" \
  B="BeatCut-$NIEUW_VERSIE.app.tar.gz" S="$1" node -e '
    const fs = require("fs");
    fs.writeFileSync(process.argv[1], JSON.stringify({
      version: process.env.V,
      notes: "lokale updatertest",
      pub_date: new Date().toISOString(),
      platforms: {
        "darwin-aarch64": { url: process.env.BASIS + "/" + process.env.B, signature: process.env.S },
        "darwin-x86_64":  { url: process.env.BASIS + "/" + process.env.B, signature: process.env.S },
      },
    }, null, 2));
  ' "$WERK/web/latest.json"
}

# ------------------------------------------------------------------ 3. de server
kop "3. lokale server op 127.0.0.1:$POORT"
maak_latest "$ECHTE_SIG"
( cd "$WERK/web" && exec python3 -m http.server "$POORT" --bind 127.0.0.1 ) >"$WERK/http.log" 2>&1 &
SERVER=$!
for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:$POORT/latest.json" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS "http://127.0.0.1:$POORT/latest.json" >/dev/null || fout "de server kwam niet op"
echo "   latest.json staat klaar"

# -------------------------------------------------------------- 4. de echte test
kop "4. $OUD_VERSIE zoekt de update (moet lukken)"
set +e
BEATCUT_UPDATE_ENDPOINT="http://127.0.0.1:$POORT/latest.json" BEATCUT_GEEN_DEV=1 \
  "$OUD_APP" --updatetest
GOED=$?
set -e
[ "$GOED" = 0 ] || fout "de update werd niet gevonden of niet opgehaald (code $GOED)"

# --------------------------------------------------------- 5. de valse handtekening
kop "5. dezelfde update met een handtekening van een andere sleutel (moet geweigerd worden)"
maak_latest "$VALSE_SIG"
set +e
BEATCUT_UPDATE_ENDPOINT="http://127.0.0.1:$POORT/latest.json" BEATCUT_GEEN_DEV=1 \
  "$OUD_APP" --updatetest
SLECHT=$?
set -e
[ "$SLECHT" = 2 ] || fout "een valse handtekening werd NIET geweigerd (code $SLECHT) — dit is ernstig"

kop "klaar"
echo "$OUD_VERSIE vond $NIEUW_VERSIE, haalde hem op, en de handtekening klopte."
echo "Een handtekening van een andere sleutel werd geweigerd."
echo "De versie in $CONF staat weer op $OUD_VERSIE."
