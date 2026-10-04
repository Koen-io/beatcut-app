"""Haal de Google Fonts die de titelstijlen nodig hebben op als woff2 + licentie.

Eenmalig gereedschap: het resultaat (brands/fonts/) gaat mee in git, zodat een
render nooit het internet nodig heeft. Opnieuw draaien mag; het overschrijft.
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

WORTEL = Path("/Users/macminiks/Code/projecten/claude-video-editor/brands/fonts")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# (map, Google-Fonts-query, map in google/fonts voor de licentie)
FAMILIES = [
    ("anton",            "Anton",                                      "ofl/anton"),
    ("archivo-black",    "Archivo+Black",                              "ofl/archivoblack"),
    ("bebas-neue",       "Bebas+Neue",                                 "ofl/bebasneue"),
    ("caveat",           "Caveat:wght@400..700",                       "ofl/caveat"),
    ("dm-sans",          "DM+Sans:wght@400..700",                      "ofl/dmsans"),
    ("dm-serif-display", "DM+Serif+Display",                           "ofl/dmserifdisplay"),
    ("fraunces",         "Fraunces:ital,wght@0,100..900;1,100..900",   "ofl/fraunces"),
    ("geist",            "Geist:wght@400..700",                        "ofl/geist"),
    ("jetbrains-mono",   "JetBrains+Mono:wght@400..700",               "ofl/jetbrainsmono"),
    ("monoton",          "Monoton",                                    "ofl/monoton"),
    ("montserrat",       "Montserrat:wght@400..900",                   "ofl/montserrat"),
    ("oswald",           "Oswald:wght@400..700",                       "ofl/oswald"),
    ("playfair-display", "Playfair+Display:ital,wght@0,400..900;1,400..900", "ofl/playfairdisplay"),
    ("poppins",          "Poppins:wght@400;700",                       "ofl/poppins"),
    ("rubik-glitch",     "Rubik+Glitch",                               "ofl/rubikglitch"),
    ("space-grotesk",    "Space+Grotesk:wght@400..700",                "ofl/spacegrotesk"),
    ("space-mono",       "Space+Mono:wght@400;700",                    "ofl/spacemono"),
    ("syne",             "Syne:wght@400..800",                         "ofl/syne"),
    ("vt323",            "VT323",                                      "ofl/vt323"),
]

# Alleen deze subsets; de rest (cyrillisch, Vietnamees, Grieks) zou het pakket
# verdubbelen zonder dat er een plaatsnaam in voorkomt die wij zetten.
SUBSETS = {"latin", "latin-ext"}


def haal(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


BLOK = re.compile(r"/\*\s*([a-z0-9-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", re.I)


def een(slug: str, query: str, licentiepad: str) -> dict:
    map_ = WORTEL / slug
    map_.mkdir(parents=True, exist_ok=True)
    css = haal(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode()

    regels, n = [], 0
    for subset, blok in BLOK.findall(css):
        if subset not in SUBSETS:
            continue
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", blok)
        if not m:
            continue
        bestandsnaam = f"{slug}-{subset}-{n}.woff2"
        (map_ / bestandsnaam).write_bytes(haal(m.group(1)))
        regels.append(blok.replace(m.group(0), f"url({slug}/{bestandsnaam})")
                      .replace("font-display: swap", "font-display: block"))
        n += 1

    # De licentie hoort naast het lettertype te staan, niet alleen in een
    # tabel in een plan-document.
    lic = None
    for naam in ("OFL.txt", "LICENSE.txt", "LICENCE.txt"):
        try:
            lic = haal(f"https://raw.githubusercontent.com/google/fonts/main/{licentiepad}/{naam}")
            (map_ / naam).write_bytes(lic)
            break
        except Exception:
            continue
    # METADATA.pb zegt officieel onder welke licentie het staat.
    try:
        meta = haal(f"https://raw.githubusercontent.com/google/fonts/main/{licentiepad}/METADATA.pb").decode()
        licentie = (re.search(r'license:\s*"([^"]+)"', meta) or [None, "?"])[1]
    except Exception:
        licentie = "?"
    return {"slug": slug, "bestanden": n, "licentie": licentie,
            "licentiebestand": bool(lic), "css": regels}


if __name__ == "__main__":
    alles, overzicht = [], []
    for slug, query, lic in FAMILIES:
        try:
            r = een(slug, query, lic)
        except Exception as e:
            print(f"MISLUKT {slug}: {e}", file=sys.stderr)
            continue
        alles.extend(r.pop("css"))
        overzicht.append(r)
        print(f"{slug:18} {r['bestanden']} woff2  licentie={r['licentie']}  "
              f"bestand={'ja' if r['licentiebestand'] else 'NEE'}")
    kop = ("/* Lettertypes voor de titelstijlen, lokaal meegeleverd.\n"
           "   Gegenereerd door installer/fonts/haal-fonts.py — niet met de hand bijwerken.\n"
           "   Alleen OFL/Apache; de licentie staat per familie in brands/fonts/<familie>/.\n"
           "   Een render mag nooit het internet nodig hebben. */\n\n")
    (WORTEL / "titelfonts.css").write_text(kop + "\n".join(alles) + "\n", encoding="utf-8")
    (WORTEL / "herkomst.json").write_text(json.dumps(overzicht, indent=1), encoding="utf-8")
