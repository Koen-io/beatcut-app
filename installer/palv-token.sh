#!/usr/bin/env bash
# Het read-only token van de P-ALV-editie op zijn drie plekken zetten.
#
#     installer/palv-token.sh github_pat_…     # bewaren, secret zetten, nakijken
#     installer/palv-token.sh --toon           # het bewaarde token laten zien
#     installer/palv-token.sh --nakijken       # alleen controleren of het nog werkt
#
# Het token is een fijnmazig GitHub-token dat alleen *Contents: lezen* mag op
# Koen-io/P-ALV-Movie-Maker-Releases. Het gaat:
#
# 1. in de login-sleutelhanger (dienst `palv-releases-token`, account `koen`),
#    zodat een lokale P-ALV-bouw (app/edities/bouw.sh) het kan inbakken;
# 2. als secret PALV_RELEASES_TOKEN in de bouwrepo Koen-io/beatcut-app, waar
#    de CI er het merkpakket mee ophaalt én het in de app bakt.
#
# Een fijnmazig token verloopt (hoogstens na een jaar). Verloopt het, dan
# zegt de app "kan zichzelf niet bijwerken; installeer met de installer" —
# maak dan een nieuw token en draai dit script opnieuw.
set -euo pipefail

DIENST="palv-releases-token"
ACCOUNT="koen"
REPO="Koen-io/P-ALV-Movie-Maker-Releases"
BOUWREPO="Koen-io/beatcut-app"

fout() { echo "palv-token.sh: $*" >&2; exit 1; }

lees() { security find-generic-password -s "$DIENST" -a "$ACCOUNT" -w 2>/dev/null || true; }

nakijken() {  # token -> 0 als het de repo kan lezen
  local token="$1" status
  status="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/releases/tags/merk")"
  [ "$status" = "200" ] || fout "het token kan $REPO niet lezen (HTTP $status)"
  echo "   het token leest $REPO (release merk gevonden)"
  # Vervaldatum, als GitHub hem meegeeft.
  curl -s -I -H "Authorization: Bearer $token" "https://api.github.com/repos/$REPO" \
    | grep -i '^github-authentication-token-expiration' | sed 's/^/   /' || true
}

case "${1:-}" in
  --toon)
    t="$(lees)"; [ -n "$t" ] || fout "geen token in de sleutelhanger"
    echo "$t" ;;
  --nakijken)
    t="$(lees)"; [ -n "$t" ] || fout "geen token in de sleutelhanger"
    nakijken "$t" ;;
  github_pat_*)
    TOKEN="$1"
    echo "== nakijken =="
    nakijken "$TOKEN"
    echo "== sleutelhanger =="
    security add-generic-password -U -s "$DIENST" -a "$ACCOUNT" -w "$TOKEN" \
      -T "" -l "P-ALV Movie Maker releases (read-only GitHub-token)"
    echo "   bewaard als $DIENST / $ACCOUNT"
    echo "== secret in $BOUWREPO =="
    command -v gh >/dev/null || fout "gh ontbreekt"
    printf '%s' "$TOKEN" | gh secret set PALV_RELEASES_TOKEN --repo "$BOUWREPO"
    gh secret list --repo "$BOUWREPO" | grep PALV_RELEASES_TOKEN | sed 's/^/   /'
    echo "Klaar. De volgende bouw in $BOUWREPO maakt ook de P-ALV Movie Maker." ;;
  *)
    fout "gebruik: installer/palv-token.sh github_pat_… | --toon | --nakijken" ;;
esac
