#!/usr/bin/env bash
#
# Bouwt ffmpeg + ffprobe voor macOS als LGPL-build, voor BeatCut.
#
#     installer/ffmpeg/bouw-mac.sh              # eigen architectuur
#     installer/ffmpeg/bouw-mac.sh x64          # expliciet
#     FORCEER=1 installer/ffmpeg/bouw-mac.sh    # opnieuw, ook als het er al staat
#
# Uitvoer: installer/uit/ffmpeg/<arch>/{ffmpeg,ffprobe}   (arch = arm64 of x64)
# Daarnaast een kopie in installer/uit/ffmpeg/huidig/, want dát pad staat in
# app/src-tauri/tauri.conf.json. Zo hoeft die niet te weten op welke machine
# hij draait.
#
# Waarom zelf bouwen:
#
# - **Geen GPL.** Homebrew-ffmpeg en de meeste kant-en-klare builds zijn
#   `--enable-gpl` met x264/x265 erin. Dat mag je niet meeleveren in een app
#   die je niet als GPL uitgeeft. Deze build is LGPL 2.1+: geen `--enable-gpl`,
#   geen x264, geen x265, geen nonfree.
# - **Geen H.264 in software dus.** Encoderen gaat via VideoToolbox
#   (`h264_videotoolbox`, `hevc_videotoolbox`). Elke Mac heeft dat.
# - **Niets van Homebrew erin.** `--disable-autodetect` zet alle optionele
#   bibliotheken uit; alleen wat hieronder expliciet aanstaat gaat mee, en dat
#   zit allemaal in macOS zelf. De controle onderaan faalt als er tóch een
#   dylib buiten /usr/lib en /System in het resultaat zit.
#
# Valkuil op deze Mac (gemeten 02-10-2026): `/usr/bin/clang` pakt de SDK van
# Command Line Tools (27.0) en de linker struikelt over de .tbd-bestanden
# daarin ("tapi error: malformed file"). Daarom zet dit script DEVELOPER_DIR en
# SDKROOT naar de SDK van Xcode. Zonder die twee faalt `configure` al bij de
# eerste testcompilatie.

set -euo pipefail

VERSIE="${FFMPEG_VERSIE:-8.1.3}"
# Vastgezet op de versie hierboven: ffmpeg.org publiceert zelf geen checksums,
# alleen GPG-signaturen. Dit pint dus de versie, het vervangt geen signatuur.
# Andere versie bouwen? Zet SOM leeg of werk hem bij.
SOM="${FFMPEG_SOM:-7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3}"

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORTEL="$(cd "$HIER/../.." && pwd)"

# --- architectuur ----------------------------------------------------------
GEVRAAGD="${1:-$(uname -m)}"
case "$GEVRAAGD" in
  arm64|aarch64) ARCH=arm64; FF_ARCH=arm64;  CLANG_ARCH=arm64;  MIN=11.0 ;;
  x64|x86_64)    ARCH=x64;   FF_ARCH=x86_64; CLANG_ARCH=x86_64; MIN=10.15 ;;
  *) echo "onbekende architectuur: $GEVRAAGD (kies arm64 of x64)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  arm64) EIGEN=arm64 ;;
  *)     EIGEN=x64 ;;
esac

WERK="$HIER/bouw"
SRC="$WERK/ffmpeg-$VERSIE"
UIT="$WORTEL/installer/uit/ffmpeg/$ARCH"
HUIDIG="$WORTEL/installer/uit/ffmpeg/huidig"

# --- staat het er al? ------------------------------------------------------
klaar_al() {
  [ -x "$UIT/ffmpeg" ] && [ -x "$UIT/ffprobe" ] || return 1
  "$UIT/ffmpeg" -hide_banner -version 2>/dev/null | head -1 | grep -q "version $VERSIE" || return 1
  "$UIT/ffmpeg" -hide_banner -buildconf 2>/dev/null | grep -q -- "--enable-gpl" && return 1
  return 0
}
if [ "${FORCEER:-0}" != "1" ] && klaar_al; then
  echo "ffmpeg $VERSIE ($ARCH) staat al in $UIT — niets te doen."
  mkdir -p "$HUIDIG"; cp -f "$UIT/ffmpeg" "$UIT/ffprobe" "$HUIDIG/"
  exit 0
fi

# --- toolchain -------------------------------------------------------------
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
if [ -z "${SDKROOT:-}" ]; then
  SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
  export SDKROOT
fi
# Bewijs dat de toolchain kan linken vóór we aan een build van tien minuten beginnen.
tmp=$(mktemp -d); printf 'int main(void){return 0;}' > "$tmp/t.c"
if ! clang -arch "$CLANG_ARCH" "-mmacosx-version-min=$MIN" "$tmp/t.c" -o "$tmp/t" 2>"$tmp/err"; then
  echo "de C-toolchain kan niet linken voor $CLANG_ARCH:" >&2; cat "$tmp/err" >&2; exit 1
fi
rm -rf "$tmp"

# --- bron ophalen ----------------------------------------------------------
mkdir -p "$WERK"
TAR="$WERK/ffmpeg-$VERSIE.tar.xz"
if [ ! -f "$TAR" ]; then
  echo "→ ophalen ffmpeg-$VERSIE.tar.xz"
  curl -fL --retry 3 --max-time 600 -o "$TAR.deel" "https://ffmpeg.org/releases/ffmpeg-$VERSIE.tar.xz"
  mv "$TAR.deel" "$TAR"
fi
if [ -n "$SOM" ]; then
  echo "$SOM  $TAR" | shasum -a 256 -c - >/dev/null || { echo "checksum klopt niet" >&2; exit 1; }
fi
if [ ! -f "$SRC/configure" ]; then
  rm -rf "$SRC"
  tar -xJf "$TAR" -C "$WERK"
fi

# --- configureren ----------------------------------------------------------
BOUW="$WERK/obj-$ARCH"
STAGE="$WERK/stage-$ARCH"
rm -rf "$STAGE"
mkdir -p "$BOUW"
cd "$BOUW"

CONF=(
  "$SRC/configure"
  --prefix="$STAGE"
  # LGPL: nergens --enable-gpl, --enable-nonfree, x264 of x265.
  --disable-autodetect          # niets van Homebrew erin
  --enable-videotoolbox         # hardware-decode en -encode
  --enable-audiotoolbox
  --enable-zlib --enable-bzlib --enable-iconv   # zitten in macOS
  # lzma staat bewust uit: macOS levert liblzma wel mee, maar lzma.h zit niet
  # in de SDK, dus configure faalt met "lzma requested but not found".
  --enable-static --disable-shared
  --disable-doc --disable-debug
  --enable-ffmpeg --enable-ffprobe --disable-ffplay --disable-sdl2
  # macOS heeft iconv in libSystem niet; het zit in libiconv en dat moet je
  # er met de hand bij linken. Zonder dit faalt de link met "_iconv_open"
  # ongedefinieerd, omdat --disable-autodetect de normale detectie uitzet.
  --extra-libs="-liconv"
  --extra-cflags="-mmacosx-version-min=$MIN"
  --extra-ldflags="-mmacosx-version-min=$MIN"
)
if [ "$ARCH" != "$EIGEN" ]; then
  # Niet gemeten; in CI bouwt elke runner zijn eigen architectuur.
  echo "let op: $ARCH op een $EIGEN-machine is kruiscompilatie en is hier niet getest."
  CONF+=(--enable-cross-compile --arch="$FF_ARCH" --target-os=darwin
         --cc="clang -arch $CLANG_ARCH")
else
  CONF+=(--arch="$FF_ARCH" --cc="clang -arch $CLANG_ARCH")
fi

echo "→ configure ($ARCH)"
"${CONF[@]}" > "$WERK/configure-$ARCH.log" 2>&1 || { tail -40 "$WERK/configure-$ARCH.log" >&2; exit 1; }

echo "→ make ($(sysctl -n hw.ncpu) kernen)"
make -j"$(sysctl -n hw.ncpu)" > "$WERK/make-$ARCH.log" 2>&1 || { tail -40 "$WERK/make-$ARCH.log" >&2; exit 1; }
make install >> "$WERK/make-$ARCH.log" 2>&1

# --- wegzetten -------------------------------------------------------------
mkdir -p "$UIT"
cp -f "$STAGE/bin/ffmpeg" "$STAGE/bin/ffprobe" "$UIT/"
strip -S -x "$UIT/ffmpeg" "$UIT/ffprobe" 2>/dev/null || true
chmod +x "$UIT/ffmpeg" "$UIT/ffprobe"

# --- controleren -----------------------------------------------------------
fout=0
for exe in "$UIT/ffmpeg" "$UIT/ffprobe"; do
  # Geen GPL in de configuratie.
  if "$exe" -hide_banner -buildconf | grep -qE -- '--enable-(gpl|nonfree)|libx26[45]'; then
    echo "FOUT: $exe is niet LGPL" >&2; fout=1
  fi
  # Niets gelinkt buiten macOS zelf.
  vreemd=$(otool -L "$exe" | tail -n +2 | awk '{print $1}' \
           | grep -vE '^(/usr/lib/|/System/Library/)' || true)
  if [ -n "$vreemd" ]; then
    echo "FOUT: $exe linkt buiten macOS:" >&2; echo "$vreemd" >&2; fout=1
  fi
done
for enc in h264_videotoolbox hevc_videotoolbox; do
  "$UIT/ffmpeg" -hide_banner -encoders 2>/dev/null | grep -q " $enc " \
    || { echo "FOUT: encoder $enc ontbreekt" >&2; fout=1; }
done
if [ "$ARCH" = "$EIGEN" ]; then
  proef=$(mktemp -d)
  "$UIT/ffmpeg" -v error -f lavfi -i testsrc=size=640x360:rate=30:duration=2 \
    -c:v h264_videotoolbox -b:v 2M -allow_sw 1 "$proef/proef.mp4" -y \
    || { echo "FOUT: proefencode met h264_videotoolbox mislukte" >&2; fout=1; }
  [ -s "$proef/proef.mp4" ] || { echo "FOUT: proefencode leverde niets op" >&2; fout=1; }
  rm -rf "$proef"
fi
[ "$fout" = 0 ] || exit 1

mkdir -p "$HUIDIG"
cp -f "$UIT/ffmpeg" "$UIT/ffprobe" "$HUIDIG/"

echo
"$UIT/ffmpeg" -hide_banner -version | head -2
du -sh "$UIT"
echo "klaar: $UIT"
