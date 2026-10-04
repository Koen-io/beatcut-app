#!/usr/bin/env bash
# release.sh — BeatCut 2 uitgeven. Naar het model van spam-buster/release.sh.
#
#     ./release.sh 0.3.1              alles: versie, tests, tag, push, bouw afwachten, publiceren
#     ./release.sh 0.3.1 --droog      precies hetzelfde, maar niets wordt gewijzigd of gepusht
#     ./release.sh 0.3.1 --niet-wachten   versie, tests, tag en push; publiceren later
#     ./release.sh --publiceer 0.3.1  alleen publiceren, voor een tag die er al staat
#     ./release.sh --publiceer 0.3.1 --droog   idem, maar alleen nakijken en opsommen
#
# `BEATCUT_ARTEFACTEN=<map>` zet een klaarstaande artefactmap in de plaats van
# `gh run download`. Samen met `--droog` loopt de publicatiestap dan door de
# echte controles en de echte verzameling heen zonder Actions en zonder GitHub;
# dat is wat tests/test_release.py gebruikt.
#
# Wat er gebeurt:
#
# 1. Het nummer gaat in vijf bestanden: tauri.conf.json, app/package.json,
#    app/src-tauri/Cargo.toml, pyproject.toml en engine/cve/__init__.py.
#    Vijf, omdat de app, de engine en de updater allemaal hun eigen versie
#    melden; lopen ze uit elkaar dan denkt de updater dat er nooit iets nieuws is.
# 2. De tests draaien: pytest, de interface en cargo test. Rood is einde
#    verhaal, er gaat niets naar buiten.
# 3. Commit + tag `v0.3.1` + push. Dat start .github/workflows/beatcut2.yml.
# 4. `gh run watch` wacht op drie runners (macOS arm64, macOS x64, Windows).
# 5. De artefacten worden opgehaald, de controlegetallen nagerekend, en
#    gepubliceerd in Koen-io/beatcut-releases met Koens eigen gh-login.
#    `latest.json` gaat mee; dat is wat de updater in de app ophaalt.
#
# Hij weigert bij een vuile werkboom, op een andere tak dan beatcut2 of main,
# bij een nummer dat niet precies X.Y.Z is, en bij een nummer dat niet hoger is
# dan wat er nu staat. Terugdraaien na een push is veel duurder dan hier stoppen.
set -euo pipefail

cd "$(dirname "$0")"

fout() { echo "release.sh: $*" >&2; exit 1; }

PUBLIEK="Koen-io/beatcut-releases"
WORKFLOW="beatcut2.yml"
CONF="app/src-tauri/tauri.conf.json"
# De bestanden waarin het versienummer staat. Met de hand opgesomd: `git add -A`
# zou werk van een andere sessie meenemen.
VERSIEBESTANDEN=(
  "$CONF"
  app/package.json
  app/src-tauri/Cargo.toml
  app/src-tauri/Cargo.lock
  pyproject.toml
  engine/cve/__init__.py
)
DROOG=false

doe() { if $DROOG; then echo "   [droog] $*"; else "$@"; fi; }

canoniek() {
  # Precies drie getallen zonder voorloopnullen. Het nummer wordt letterlijk de
  # bestandsnaam van de installer en staat in latest.json, dus "0.03.1" mag
  # nooit stilletjes "0.3.1" worden.
  printf '%s' "$1" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
}

hoger_dan() {  # is $1 hoger dan $2?
  [ "$1" != "$2" ] &&
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)" = "$2" ]
}

zet_versie() {  # nieuw -> de vijf bestanden bijwerken
  local nieuw="$1"
  if $DROOG; then
    echo "   [droog] versie $nieuw in ${VERSIEBESTANDEN[*]}"
    return 0
  fi
  python3 - "$nieuw" <<'PY'
import json, re, sys
from pathlib import Path

nieuw = sys.argv[1]

for pad in (Path("app/src-tauri/tauri.conf.json"), Path("app/package.json")):
    data = json.loads(pad.read_text())
    data["version"] = nieuw
    pad.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

# Alleen de eerste regel; in Cargo.toml staat die onder [package] en mag een
# version= van een dependency niet geraakt worden.
for pad, sleutel in (
    (Path("app/src-tauri/Cargo.toml"), "version"),
    (Path("pyproject.toml"), "version"),
    (Path("engine/cve/__init__.py"), "__version__"),
):
    tekst, aantal = re.subn(
        rf'(?m)^{sleutel} = "[^"]+"', f'{sleutel} = "{nieuw}"', pad.read_text(), count=1
    )
    if aantal != 1:
        raise SystemExit(f"versie niet gevonden in {pad}")
    pad.write_text(tekst)
PY
  # Cargo.lock meenemen, anders klaagt een build met --locked.
  ( cd app/src-tauri && cargo update -p beatcut --precise "$nieuw" >/dev/null 2>&1 ) || true
  echo "   versie $nieuw gezet"
}

# Elke versie is ~650 MB aan installers. De updater kijkt alleen naar de
# nieuwste; drie houden we voor terugvallen. Oudere gaan weg, met hun tag.
BEWAAR=3
ruim_op() {
  local oud
  oud=$(gh release list --repo "$PUBLIEK" --limit 100 --json tagName,createdAt \
        --jq "sort_by(.createdAt) | reverse | .[$BEWAAR:] | .[].tagName")
  [ -n "$oud" ] || return 0
  echo "== opruimen: alleen de nieuwste $BEWAAR releases blijven =="
  for t in $oud; do
    echo "   weg: $t"
    doe gh release delete "$t" --repo "$PUBLIEK" --yes --cleanup-tag
  done
}

publiceer() {  # versie -> wacht op Actions, controleer, publiceer
  local versie="$1" run="" map notes vorig dubbel b eigen=false

  if [ -n "${BEATCUT_ARTEFACTEN:-}" ]; then
    [ -d "$BEATCUT_ARTEFACTEN" ] || fout "BEATCUT_ARTEFACTEN is geen map"
    map="$BEATCUT_ARTEFACTEN"
    eigen=true
    echo "== artefacten uit $map (BEATCUT_ARTEFACTEN) =="
  elif $DROOG; then
    echo "   [droog] wachten op de run van v$versie en de artefacten ophalen"
    echo "   [droog] zet BEATCUT_ARTEFACTEN=<map> om de verzameling écht na te kijken"
    return 0
  else
    command -v gh >/dev/null || fout "gh ontbreekt"
    echo "== wachten op de bouw (drie runners: ffmpeg, tests, PyInstaller, Tauri; ~20 minuten) =="
    for _ in $(seq 1 60); do
      run="$(gh run list --workflow="$WORKFLOW" --branch "v$versie" --limit 1 \
               --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
      [ -n "$run" ] && break
      sleep 5
    done
    [ -n "$run" ] || fout "geen Actions-run gevonden voor v$versie"
    gh run watch "$run" --exit-status >/dev/null \
      || fout "de bouw is rood (run $run) — niets gepubliceerd"

    if gh release view "v$versie" --repo "$PUBLIEK" >/dev/null 2>&1; then
      echo "== v$versie staat al in $PUBLIEK =="
      return 0
    fi

    echo "== artefacten ophalen en controleren =="
    map="$(mktemp -d)"
    gh run download "$run" -D "$map" || fout "artefacten niet gevonden"
  fi
  for deel in "$map"/beatcut-*; do
    ( cd "$deel" && shasum -a 256 -c SHA256SUMS ) \
      || fout "controlegetal klopt niet in $(basename "$deel"); niets gepubliceerd"
  done
  [ -f "$map/latest-json/latest.json" ] || fout "latest.json ontbreekt; de updater zou niets vinden"
  # De drie platformen moeten erin staan, anders werkt een deel van de
  # installaties zich nooit bij.
  node -e '
    const j = require(process.argv[1]);
    const nodig = ["darwin-aarch64", "darwin-x86_64", "windows-x86_64"];
    const mist = nodig.filter((p) => !j.platforms?.[p]?.signature);
    if (mist.length) { console.error("latest.json mist: " + mist); process.exit(1); }
    if (j.version !== process.argv[2]) { console.error("latest.json zegt " + j.version); process.exit(1); }
  ' "$map/latest-json/latest.json" "$versie" || fout "latest.json is niet in orde"

  vorig="$(git describe --tags --abbrev=0 --match 'v*' "v$versie^" 2>/dev/null || true)"
  notes=""
  if [ -n "$vorig" ]; then
    notes="$(git log --no-merges --format='- %s' "$vorig..v$versie" | grep -v '^- Release ' || true)"
  fi
  [ -n "$notes" ] || notes="- Onderhoudsrelease."

  # Wat eruit gaat: de drie bundels met hun `.sig`, één `SHA256SUMS` en
  # `latest.json`. Niets uit `sig-*/` — dat zijn kopieën voor de job `latest`:
  # een tweede `.sig` met dezelfde naam en drie keer `bestandsnaam.txt`.
  # GitHub weigert twee assets die hetzelfde heten, en dan stopt de publicatie
  # halverwege terwijl een herpoging stuit op "release bestaat al".
  cat "$map"/beatcut-*/SHA256SUMS > "$map/SHA256SUMS"
  bestanden=()
  while IFS= read -r b; do bestanden+=("$b"); done < <(
    find "$map"/beatcut-* -type f ! -name SHA256SUMS | sort
    echo "$map/latest-json/latest.json"
    echo "$map/SHA256SUMS"
  )
  [ "${#bestanden[@]}" -eq 8 ] \
    || fout "verwacht 3 bundels + 3 handtekeningen + latest.json + SHA256SUMS, kreeg ${#bestanden[@]}"
  dubbel="$(for b in "${bestanden[@]}"; do basename "$b"; done | sort | uniq -d)"
  [ -z "$dubbel" ] || fout "dubbele assetnaam, GitHub weigert dat: $(echo "$dubbel" | tr '\n' ' ')"

  if $DROOG; then
    echo "   [droog] gh release create v$versie --repo $PUBLIEK met:"
    for b in "${bestanden[@]}"; do echo "      $(basename "$b")"; done
    return 0
  fi

  echo "== publiceren in $PUBLIEK =="
  command -v gh >/dev/null || fout "gh ontbreekt"
  gh release create "v$versie" --repo "$PUBLIEK" --target main \
    --title "BeatCut $versie" \
    --notes "$(printf '%s\n\nmacOS vraagt bij de eerste start één keer om bevestiging (Systeeminstellingen › Privacy en beveiliging › Toch openen). Windows kan een SmartScreen-melding geven: Meer info → Toch uitvoeren.\nWie BeatCut al heeft, krijgt deze versie automatisch aangeboden.' "$notes")" \
    "${bestanden[@]}"
  ruim_op
  $eigen || rm -rf "$map"
}

# ---------------------------------------------------------------- --publiceer
if [ "${1:-}" = "--publiceer" ]; then
  NIEUW="${2:-}"
  canoniek "${NIEUW:-}" || fout "geef het versienummer mee: ./release.sh --publiceer 0.3.1"
  case "${3:-}" in
    --droog) DROOG=true ;;
    "")      ;;
    *)       fout "onbekende optie '${3}'" ;;
  esac
  if ! $DROOG; then
    git rev-parse -q --verify "refs/tags/v$NIEUW" >/dev/null || fout "tag v$NIEUW bestaat hier niet"
  fi
  publiceer "$NIEUW"
  echo
  if $DROOG; then
    echo "DROOG klaar — er is niets gepubliceerd."
  else
    echo "Klaar: https://github.com/$PUBLIEK/releases/latest"
  fi
  exit 0
fi

# ---------------------------------------------------------------- releasen
NIEUW="${1:-}"
[ -n "$NIEUW" ] || fout "geef het versienummer mee, bijvoorbeeld: ./release.sh 0.3.1"
canoniek "$NIEUW" || fout "'$NIEUW' moet X.Y.Z zijn, zonder voorloopnullen"
WACHTEN=true
case "${2:-}" in
  --droog)        DROOG=true ;;
  --niet-wachten) WACHTEN=false ;;
  "")             ;;
  *)              fout "onbekende optie '${2}'" ;;
esac
if $DROOG; then echo "== DROOG: er wordt niets gewijzigd, niets gecommit en niets gepusht =="; fi

TAK="$(git rev-parse --abbrev-ref HEAD)"
case "$TAK" in
  beatcut2|main) ;;
  *) fout "je staat op '$TAK'; releasen gebeurt op beatcut2 of main" ;;
esac

if [ -n "$(git status --porcelain)" ]; then
  git status --short >&2
  if $DROOG; then
    echo "   [droog] de werkboom is niet schoon; echt releasen zou hier stoppen"
  else
    fout "de werkboom is niet schoon — commit, negeer of stash eerst"
  fi
fi

OUD="$(node -p "require('./$CONF').version")"
canoniek "$OUD" || fout "de versie in $CONF ($OUD) is geen X.Y.Z"
hoger_dan "$NIEUW" "$OUD" || fout "$NIEUW is niet hoger dan de huidige versie $OUD"
if git rev-parse -q --verify "refs/tags/v$NIEUW" >/dev/null; then
  fout "tag v$NIEUW bestaat al"
fi

# De versies moeten nú gelijk staan; anders is een eerdere release halverwege
# gestopt en zou dit script dat verschil meenemen.
echo "== versies nakijken =="
for pad in app/package.json app/src-tauri/Cargo.toml pyproject.toml engine/cve/__init__.py; do
  gevonden="$(grep -m1 -E '^\s*"?(version|__version__)"?\s*[:=]' "$pad" \
              | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  [ "$gevonden" = "$OUD" ] || fout "$pad staat op '$gevonden', $CONF op '$OUD' — zet die eerst gelijk"
done
echo "   alle vijf op $OUD"

echo "== tests =="
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
"$PY" -m pytest -q || fout "pytest is niet groen; er gaat niets naar buiten"
( cd app && npm run build >/dev/null ) || fout "de interface bouwt niet"
( cd app/src-tauri && cargo test --quiet >/dev/null ) || fout "cargo test is niet groen"
echo "   pytest, npm run build en cargo test zijn groen"

echo "== $OUD -> $NIEUW =="
zet_versie "$NIEUW"
doe git add "${VERSIEBESTANDEN[@]}"
doe git commit -q -m "Release $NIEUW"
doe git tag -a "v$NIEUW" -m "Release $NIEUW"
doe git push origin "$TAK" --follow-tags
if ! $DROOG; then echo "Gepusht. De bouw loopt."; fi

if ! $WACHTEN; then
  echo "Niet gewacht. Publiceren kan later met: ./release.sh --publiceer $NIEUW"
  exit 0
fi

publiceer "$NIEUW"
echo
if $DROOG; then
  echo "DROOG klaar — er is niets gewijzigd en niets gepusht."
else
  echo "Klaar: https://github.com/$PUBLIEK/releases/latest"
fi
