# Software en gegevens van derden in BeatCut

BeatCut bouwt op het werk van anderen. Hieronder staat wat er meegaat in de
app, of wat de app op jouw verzoek ophaalt, met de licentie.

## Meegeleverd in de app

| Onderdeel | Licentie | Waarvoor |
|---|---|---|
| FFmpeg 8.1.3 (eigen LGPL-build, zonder GPL- of nonfree-onderdelen) | LGPL 2.1 of later | decoderen, encoderen, audio |
| wgpu, pollster, serde, bytemuck (Rust) | MIT / Apache 2.0 | de compositor (kleur, afwerking, overgangen) |
| Tauri 2 | MIT / Apache 2.0 | het app-venster |
| React | MIT | de interface |
| mp4box.js | BSD 3-Clause | de live voorvertoning |
| GSAP 3 | GreenSock Standard "no charge" License | animatie van de titels |
| Python, NumPy, OpenCV, librosa, numba, PySceneDetect, soundfile | PSF / BSD / Apache 2.0 / ISC | analyse van beeld en geluid |
| 19 lettertypen (zie `brands/fonts/herkomst.json`) | SIL Open Font License 1.1 | titels |
| GeoNames-plaatsenlijst (cities15000, uitgekleed) | CC BY 4.0 — © GeoNames, geonames.org | plaatsnamen in titels |

De 24 looks (`looks/*.cube`) en de 14 montagestijlen en 20 titelstijlen zijn
eigen werk.

**FFmpeg.** BeatCut gebruikt FFmpeg als los programma; de app linkt er niet
tegenaan. De broncode van precies deze versie is op te halen bij
<https://ffmpeg.org/releases/ffmpeg-8.1.3.tar.xz>; het bouwscript staat in
`installer/ffmpeg/`. Op Windows gaat een LGPL-build van BtbN mee
(<https://github.com/BtbN/FFmpeg-Builds>).

## Op jouw verzoek opgehaald

| Onderdeel | Licentie | Wanneer |
|---|---|---|
| ACE-Step 1.5 (code en modelgewichten) | MIT | eenmalig, als je muziek wilt maken (~11 GB) |
| uv (Astral) | MIT / Apache 2.0 | samen met ACE-Step |
| Node.js | MIT | eenmalig, voor titels in de export |
| HyperFrames | Apache 2.0 | idem |
| Chrome headless shell | BSD 3-Clause (Chromium) | idem |

Muziek die ACE-Step op jouw computer maakt is van jou; er hoort geen
naamsvermelding bij.
