#!/usr/bin/env bash
# Zet de huidige commit als opgeschoonde momentopname in de publieke bouwrepo.
#
# Waarom: GitHub-bouwminuten zijn gratis en onbeperkt voor publieke repo's,
# en de Mac-runners kostten in de privé-repo 10x zoveel (03-10-2026 op).
# De privé-repo `Koen-io/beatcut` blijft de werkplaats met alle geschiedenis;
# `Koen-io/beatcut-app` krijgt alleen wat nodig is om te bouwen en te testen.
#
# Niet mee (privé of persoonlijk): projecten/ (eigen beelden, GPS, transcripten),
# ontwerp/ behalve de iconen, historie/, projectgeheugen/, en de interne
# werknotities in de hoofdmap.
#
#   installer/publiek.sh            # momentopname van HEAD pushen
#   installer/publiek.sh --droog    # alleen laten zien wat er mee zou gaan
set -euo pipefail
cd "$(dirname "$0")/.."

PUBLIEK="Koen-io/beatcut-app"
DROOG=false
[[ "${1:-}" == "--droog" ]] && DROOG=true

# Alleen wat gecommit is gaat mee (git archive HEAD); werk in uitvoering niet.
BRON=$(git rev-parse --short HEAD)
WERK=$(mktemp -d)
trap 'rm -rf "$WERK"' EXIT

git archive HEAD | tar -x -C "$WERK/"
(
  cd "$WERK"
  rm -rf projecten historie projectgeheugen
  find ontwerp -mindepth 1 -maxdepth 1 ! -name beatcut2 -exec rm -rf {} + 2>/dev/null || true
  find ontwerp/beatcut2 -mindepth 1 -maxdepth 1 ! -name icoon -exec rm -rf {} + 2>/dev/null || true
  rm -f AGENTS.md CLAUDE.md OVERDRACHT.md HISTORIE.md PLAN.md PLAN-v2.md valkuilen-historie.md
  # Zegt waar de ondertekensleutel op de Mac staat; hoort niet publiek.
  rm -f installer/LEESMIJ.md
)

# Vangrail: niets wat naar beelden van mensen, sleutels of persoonlijke
# notities ruikt mag mee.
if find "$WERK" -type f \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.key' \
     -o -iname '*.pem' -o -iname '.env*' \) | grep -q .; then
  echo "publiek.sh: verboden bestandstype in de momentopname" >&2; exit 1
fi

if $DROOG; then
  (cd "$WERK" && find . -type f | sed 's#^\./##' | cut -d/ -f1 | sort | uniq -c)
  echo "droog: er is niets gepusht"
  exit 0
fi

KLOON=$(mktemp -d)
gh repo clone "$PUBLIEK" "$KLOON" -- --quiet 2>/dev/null || {
  git -C "$KLOON" init -q -b main
  git -C "$KLOON" remote add origin "git@github.com:$PUBLIEK.git"
}
# Alles vervangen door de momentopname (ook verwijderde bestanden gaan weg).
find "$KLOON" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$WERK/." "$KLOON/"
git -C "$KLOON" add -A
if git -C "$KLOON" diff --cached --quiet; then
  echo "publiek.sh: niets veranderd sinds de vorige momentopname"
else
  git -C "$KLOON" commit -q -m "Momentopname van beatcut@$BRON"
fi
git -C "$KLOON" push -q origin HEAD:main
echo "$PUBLIEK bijgewerkt naar beatcut@$BRON"
echo "$KLOON"
