#!/usr/bin/env bash
# Het merkpakket van een editie naar haar privé-releases-repo brengen.
#
#     installer/merkpakket.sh p-alv            # inpakken en uploaden
#     installer/merkpakket.sh p-alv --droog    # alleen inpakken en opsommen
#
# Waarom: de bouw draait in de publieke repo Koen-io/beatcut-app (gratis
# bouwminuten), en daar mag het logo van de Afdeling Luchtvaart niet in.
# `publiek.sh` laat app/edities/p-alv/ dus weg; de CI haalt het als zip uit de
# release `merk` van Koen-io/P-ALV-Movie-Maker-Releases, met het read-only
# token PALV_RELEASES_TOKEN. Verander je iets in app/edities/p-alv/ (logo,
# kleuren, config), draai dit dan opnieuw — anders bouwt de CI met het oude.
set -euo pipefail
cd "$(dirname "$0")/.."

EDITIE="${1:-}"
DROOG=false
[ "${2:-}" = "--droog" ] && DROOG=true
[ -n "$EDITIE" ] || { echo "gebruik: installer/merkpakket.sh <editie> [--droog]" >&2; exit 2; }
MAP="app/edities/$EDITIE"
[ -f "$MAP/editie.json" ] || { echo "merkpakket.sh: $MAP is geen editie" >&2; exit 2; }
[ "$EDITIE" != "beatcut" ] || { echo "merkpakket.sh: beatcut staat gewoon in de repo" >&2; exit 2; }

# Waar de editie haar releases heeft, uit editie.json.
REPO="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["updates"]["repo"])' "$MAP/editie.json")"

WERK="$(mktemp -d)"
trap 'rm -rf "$WERK"' EXIT
ZIP="$WERK/merkpakket-$EDITIE.zip"
# Alles in de editiemap, behalve wat de bouw niet nodig heeft (bron/ is het
# aangeleverde origineel; android/ios maakt `tauri icon` maar bouwen we niet).
( cd app/edities && zip -qr "$ZIP" "$EDITIE" -x "$EDITIE/bron/*" "$EDITIE/icons/android/*" "$EDITIE/icons/ios/*" "*/.DS_Store" )
echo "merkpakket: $(du -h "$ZIP" | cut -f1) voor $EDITIE → $REPO (release merk)"
unzip -l "$ZIP" | awk 'NR>3 && $4 != "" {print "   " $4}' | grep -v '^   $' | head -40

if $DROOG; then echo "droog: niets geüpload"; exit 0; fi

command -v gh >/dev/null || { echo "gh ontbreekt" >&2; exit 1; }
if ! gh release view merk --repo "$REPO" >/dev/null 2>&1; then
  gh release create merk --repo "$REPO" --title "Merkpakket (geen versie)" \
    --notes "Het merkpakket van de $EDITIE-editie: logo, kleuren, iconen en Tauri-config. De CI in Koen-io/beatcut-app haalt dit op bij elke bouw. Geen app-versie — die staan onder v*." \
    --latest=false --prerelease
fi
gh release upload merk --repo "$REPO" "$ZIP" --clobber
echo "geüpload: $REPO → merk → merkpakket-$EDITIE.zip"
