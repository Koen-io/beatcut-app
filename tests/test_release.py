"""Wat `release.sh` naar GitHub zou sturen.

De bouwstraat levert per platform twee artefacten: `beatcut-<naam>/` met de
bundel, de handtekening en een `SHA256SUMS`, en `sig-<naam>/` met een kopie
van die handtekening plus een `bestandsnaam.txt` — klein, zodat de job
`latest` geen dmg van 200 MB hoeft te downloaden. Werden die kopieën
meegepubliceerd, dan staan er twee assets met dezelfde naam en drie met de
naam `bestandsnaam.txt`. GitHub weigert dat: de publicatie stopt halverwege
en een herpoging stuit daarna op "release bestaat al".

Getest met `--droog` op een nagebootste artefactmap, dus zonder Actions, zonder
netwerk en zonder iets te publiceren.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

# release.sh draait alleen op Koens Mac (shasum, gh, bash); op de Windows-runner
# bestaat die keten niet en zegt een rode test niets over de app.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="release.sh is macOS-gereedschap")

WORTEL = Path(__file__).resolve().parents[1]
VERSIE = "0.3.1"
# (artefactmap, platform, updaterbundel, installer-zonder-sig-of-None): op
# macOS zijn het er twee (dmg voor de installatie, app.tar.gz voor de updater),
# op Windows is de setup.exe allebei.
PLATFORMEN = (
    ("mac-arm", "darwin-aarch64", f"BeatCut-{VERSIE}-arm64.app.tar.gz", f"BeatCut-{VERSIE}-arm64.dmg"),
    ("mac-x64", "darwin-x86_64", f"BeatCut-{VERSIE}-x64.app.tar.gz", f"BeatCut-{VERSIE}-x64.dmg"),
    ("win", "windows-x86_64", f"BeatCut-setup-{VERSIE}-x64.exe", None),
)


@pytest.fixture
def artefactmap(tmp_path):
    """Precies wat `gh run download` neerzet, met de dubbele namen erin."""
    latest = {"version": VERSIE, "platforms": {}}
    for naam, platform, bundel, dmg in PLATFORMEN:
        deel = tmp_path / f"beatcut-{naam}"
        deel.mkdir()
        (deel / bundel).write_bytes(b"update " + naam.encode())
        (deel / f"{bundel}.sig").write_text("handtekening", encoding="utf-8")
        if dmg:
            (deel / dmg).write_bytes(b"installer " + naam.encode())
        subprocess.run(
            f'cd "{deel}" && shasum -a 256 ./* > SHA256SUMS',
            shell=True, check=True, capture_output=True,
        )
        # De kleine kopie voor de job `latest` — hier zat het probleem.
        hulp = tmp_path / f"sig-{naam}"
        hulp.mkdir()
        (hulp / f"{bundel}.sig").write_text("handtekening", encoding="utf-8")
        (hulp / "bestandsnaam.txt").write_text(bundel, encoding="utf-8")
        latest["platforms"][platform] = {"signature": "handtekening", "url": bundel}

    (tmp_path / "latest-json").mkdir()
    (tmp_path / "latest-json" / "latest.json").write_text(
        json.dumps(latest), encoding="utf-8"
    )
    return tmp_path


def _droog(artefactmap) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["./release.sh", "--publiceer", VERSIE, "--droog"],
        cwd=WORTEL, capture_output=True, text=True, timeout=120,
        env={**os.environ, "BEATCUT_ARTEFACTEN": str(artefactmap)},
    )


def test_alleen_de_bundels_hun_sig_latest_en_een_sha256sums(artefactmap):
    r = _droog(artefactmap)
    assert r.returncode == 0, r.stdout + r.stderr

    genoemd = sorted(
        regel.strip() for regel in r.stdout.splitlines() if regel.startswith("      ")
    )
    verwacht = sorted(
        [b for _, _, b, _ in PLATFORMEN]
        + [f"{b}.sig" for _, _, b, _ in PLATFORMEN]
        + [d for _, _, _, d in PLATFORMEN if d]
        + ["SHA256SUMS", "latest.json"]
    )
    assert genoemd == verwacht, r.stdout
    assert len(genoemd) == len(set(genoemd)), "dubbele assetnamen"
    assert "bestandsnaam.txt" not in r.stdout


def test_een_dubbele_naam_laat_het_script_stoppen(artefactmap):
    """De vangrail zelf: zou er ooit tóch een dubbele naam bij komen, dan
    weigert het script in plaats van halverwege te stoppen bij GitHub."""
    arm, x64 = PLATFORMEN[0][2], PLATFORMEN[1][2]
    deel = artefactmap / "beatcut-mac-x64"
    (deel / x64).rename(deel / arm)          # zelfde naam, ander bestand
    (deel / f"{x64}.sig").rename(deel / f"{arm}.sig")
    (deel / "SHA256SUMS").unlink()
    subprocess.run(
        f'cd "{deel}" && shasum -a 256 ./* > SHA256SUMS',
        shell=True, check=True, capture_output=True,
    )

    r = _droog(artefactmap)
    assert r.returncode != 0
    assert "dubbele assetnaam" in r.stderr, r.stderr


PALV = (
    ("macos-arm64", "darwin-aarch64", f"P-ALV-Movie-Maker-{VERSIE}-arm64.app.tar.gz", f"P-ALV-Movie-Maker-{VERSIE}-arm64.dmg"),
    ("macos-x64", "darwin-x86_64", f"P-ALV-Movie-Maker-{VERSIE}-x64.app.tar.gz", f"P-ALV-Movie-Maker-{VERSIE}-x64.dmg"),
    ("windows-x64", "windows-x86_64", f"P-ALV-Movie-Maker-setup-{VERSIE}-x64.exe", None),
)


@pytest.fixture
def met_palv(artefactmap):
    """Dezelfde bouw, maar nu ook met de tweede editie erbij: `palv-<naam>/`
    en een latest.json waarvan de URL's nog `asset:<naam>` zijn."""
    latest = {"version": VERSIE, "platforms": {}}
    for naam, platform, bundel, dmg in PALV:
        deel = artefactmap / f"palv-{naam}"
        deel.mkdir()
        (deel / bundel).write_bytes(b"update " + naam.encode())
        (deel / f"{bundel}.sig").write_text("handtekening", encoding="utf-8")
        if dmg:
            (deel / dmg).write_bytes(b"installer " + naam.encode())
        subprocess.run(
            f'cd "{deel}" && shasum -a 256 ./* > SHA256SUMS',
            shell=True, check=True, capture_output=True,
        )
        latest["platforms"][platform] = {"signature": "handtekening", "url": f"asset:{bundel}"}
    (artefactmap / "latest-palv-json").mkdir()
    (artefactmap / "latest-palv-json" / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    return artefactmap


def test_de_palv_editie_gaat_naar_de_prive_repo(met_palv):
    r = _droog(met_palv)
    assert r.returncode == 0, r.stdout + r.stderr
    uit = r.stdout
    # Twee releases, twee repo's — en de privé-repo krijgt latest.json pas na
    # het invullen van de asset-adressen.
    assert "--repo Koen-io/beatcut-releases met:" in uit
    assert "--repo Koen-io/P-ALV-Movie-Maker-Releases met:" in uit
    palv_blok = uit.split("P-ALV-Movie-Maker-Releases met:")[1]
    for _, _, bundel, dmg in PALV:
        assert bundel in palv_blok and f"{bundel}.sig" in palv_blok
        if dmg:
            assert dmg in palv_blok
    assert "latest.json (na het invullen" in palv_blok
    # Niets van P-ALV lekt in de publieke release.
    publiek_blok = uit.split("beatcut-releases met:")[1].split("P-ALV-Movie-Maker-Releases met:")[0]
    publiek = [r.strip() for r in publiek_blok.splitlines() if r.startswith("      ")]
    assert publiek and not any("P-ALV" in r for r in publiek), publiek


def test_zonder_palv_artefacten_zegt_het_script_dat(artefactmap):
    r = _droog(artefactmap)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "P-ALV-Movie-Maker-Releases" not in r.stdout


def test_palv_latest_json_moet_asset_verwijzingen_hebben(met_palv):
    """Een latest.json met echte URL's uit de CI zou wijzen naar bestanden die
    in een privé-repo niet zonder token te lezen zijn; het script weigert."""
    pad = met_palv / "latest-palv-json" / "latest.json"
    j = json.loads(pad.read_text(encoding="utf-8"))
    j["platforms"]["darwin-aarch64"]["url"] = "https://github.com/x/y/releases/download/v1/a.tar.gz"
    pad.write_text(json.dumps(j), encoding="utf-8")
    r = _droog(met_palv)
    assert r.returncode != 0
    assert "P-ALV" in r.stderr
