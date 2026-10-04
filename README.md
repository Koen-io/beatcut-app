# BeatCut Video Editor

Zet je beelden en een muzieknummer in een map. Er komt een gemonteerde video
uit — beat-synchroon, met titels, ondertitels en kleurbewerking. Alles draait
op je eigen computer; er gaat niets naar buiten.

![licentie](https://img.shields.io/badge/licentie-priv%C3%A9-lightgrey)

## Twee wegen naar binnen

**Maak mijn video** — bestanden erin, drie vragen, klaar. De editor kiest de
beelden, knipt op de muziek en zet de titels erbij.

**Zelf monteren** — de volledige editor: tijdlijn, shots ruilen, titels,
overgangen, en een voorvertoning van alles wat je verandert.

## Wat het onderscheidt

- **Alles ligt op de beat.** 53 van 53 snedes binnen één frame, gemiddelde
  afwijking 0 ms.
- **Framevast.** Wat de montage voorschrijft is precies wat de render oplevert.
- **Het kijkt zichzelf na.** `cve review` meet frameaantal, zwart beeld,
  onbedoelde stilstand, luidheid, beat-afwijking en scherpte — mechanisch,
  zonder model.
- **Het leert je smaak.** Elke vervanging in de editor stelt de gewichten van
  je stijl bij.
- **Titels uit je eigen bestanden.** Opnamelocatie en -datum worden
  plaatsnamen: "Garmisch-Partenkirchen · 700 m".
- **Geluid op de aanlevernorm.** −14 LUFS, true peak onder −1 dBTP.

## Installeren

Haal de nieuwste versie onder [Releases](../../releases):

| Platform | Bestand |
|---|---|
| macOS | `BeatCut-<versie>.dmg` — openen, naar Programma's slepen |
| Windows | `BeatCut-setup-<versie>.exe` — dubbelklikken |

`ffmpeg` moet apart geïnstalleerd zijn. Het taalmodel voor ondertitels en de
plaatsenlijst worden opgehaald wanneer je ze voor het eerst gebruikt.

## Vanuit de broncode

```bash
uv venv --python 3.12 && uv pip install -e .
.venv/bin/cve doctor        # controleer de installatie
.venv/bin/cve studio        # open de editor
```

Alles in één keer vanaf de commandoregel:

```bash
.venv/bin/cve maak vakantie --stijl reis --duur 75
```

## Hoe het in elkaar zit

```
bronnen ──▶ ingest ──▶ analyse ──▶ regie ──▶ edl.json ──▶ render ──▶ review
                                      ▲                                │
                                      └──────── Studio / wizard ◀──────┘
```

`edl.json` is de enige waarheid. Chat, interface en renderer praten allemaal
via dat bestand — daarom snapt de editor wat je in de tijdlijn versleept, en
andersom.

**Alles wat een computer kan meten, meet de computer.** Scherpte, belichting,
beweging, shake, beats, spraak, locatie: allemaal mechanisch. Een model
beslist hoogstens over smaak, en is nooit vereist — de engine draait volledig
offline.

Meer over de architectuur staat in `PLAN.md`, de stand van zaken in
`CLAUDE.md`, en de weg naar de installers in `installer/LEESMIJ.md`.

## Licenties

De engine leunt op ffmpeg (LGPL), whisper.cpp (MIT), PySceneDetect (BSD-3),
OpenCV (Apache 2.0), librosa (ISC) en HyperFrames (Apache 2.0). Plaatsnamen
komen van [GeoNames](https://www.geonames.org/) (CC BY 4.0).
