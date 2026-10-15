#!/bin/sh
# Bouwt een losstaande whisper-cli voor in de app (15-10-2026).
#
# Waarom: ondertitels (spraak.py) hebben whisper.cpp nodig. Vanuit de broncode
# staat die in vendor/whisper.cpp/build, maar die binary hangt aan zes
# dylibs via @rpath en ging nooit mee in de app — de spraakkaart zei daar
# "Spraakherkenning staat niet op deze computer" en er was niets aan te doen.
#
# Statisch gelinkt (BUILD_SHARED_LIBS=OFF) en met de Metal-shaders in de
# binary zelf: één bestand, alleen systeembibliotheken. GGML_NATIVE=OFF: geen
# instructies van déze bouwmachine (M4, of AVX-512 op de CI), anders crasht hij
# met SIGILL op een oudere Mac (review 15-10-2026); Metal doet het zware werk.
# Het model komt er niet bij (574 MB); dat haalt spraakinstall.py op bij het
# eerste gebruik.
#
# Uitvoer: installer/uit/whisper/whisper-cli
set -eu

VERSIE=v1.9.2
WORTEL=$(cd "$(dirname "$0")/../.." && pwd)
BRON="$WORTEL/vendor/whisper.cpp"
BOUW="$BRON/build-statisch"
UIT="$WORTEL/installer/uit/whisper"

if [ ! -f "$BRON/CMakeLists.txt" ]; then
  git clone --depth 1 --branch "$VERSIE" https://github.com/ggml-org/whisper.cpp "$BRON"
fi

# De SDK die bij de gekozen linker hoort. Op Koens Mac wees `xcrun` naar de
# SDK van de Command Line Tools (macOS 27), terwijl `ld` uit Xcode kwam en
# die .tbd-bestanden niet kon lezen ("unknown architecture arm64e.x1").
SDK=${SDKROOT:-"$(xcode-select -p)/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"}
[ -d "$SDK" ] || SDK=$(xcrun --sdk macosx --show-sdk-path)

cmake -S "$BRON" -B "$BOUW" \
  -DCMAKE_OSX_SYSROOT="$SDK" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_METAL=ON \
  -DGGML_METAL_EMBED_LIBRARY=ON \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0
cmake --build "$BOUW" --config Release --target whisper-cli -j

mkdir -p "$UIT"
cp -f "$BOUW/bin/whisper-cli" "$UIT/whisper-cli"

# Controle: niets anders dan systeembibliotheken.
if otool -L "$UIT/whisper-cli" | tail -n +2 | grep -v -e '^\s*/usr/lib/' -e '^\s*/System/Library/'; then
  echo "whisper-cli hangt nog aan een niet-systeembibliotheek (zie hierboven)" >&2
  exit 1
fi
"$UIT/whisper-cli" --help >/dev/null 2>&1 || { echo "whisper-cli start niet" >&2; exit 1; }
echo "klaar: $UIT/whisper-cli"
