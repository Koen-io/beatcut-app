# BeatCut Video Editor

Een lokale video-editor die van een map met clips en één muziektrack een gemonteerde video maakt
waarin elke snede op de beat valt. Ontstaan uit de vraag: kan een computer het saaie deel van
monteren zelf doen, zonder dat er beelden naar een cloud gaan?

De projectmap heet nog `claude-video-editor` en het commando nog `cve`. Interne namen, bewust
niet hernoemd.

## Stand van zaken

| | |
|---|---|
| Status | in aanbouw, maar werkend eind-tot-eind |
| Sinds | augustus 2026 |
| Draait op | de Mac Mini; als `BeatCut.app` ook zonder Python of terminal |
| Laatst aangeraakt | 11 augustus 2026 (fase 0 t/m 8 afgerond op één dag-reeks) |

Repo: `github.com/Koen-io/beatcut`, privé, 60 bestanden / 784 KB.

## Waar het over ging

**De centrale keuze: meten waar het kan, oordelen waar het moet.** Alles wat een computer kan
uitrekenen — scherpte, belichting, beweging, shake, BPM, maten, drops, gezichten, lux uit de
Apple-telemetrie — doet Python. Een model beslist alleen over smaak. Dat scheelt niet alleen
tokens; het maakt het resultaat reproduceerbaar en de werk-editie volledig offline draaibaar.

**`edl.json` is de enige waarheid.** Chat, GUI en renderer praten allemaal via dat ene bestand.
Zonder die regel had elk onderdeel zijn eigen halve staat bijgehouden.

**Waar het echte werk zat: framevastheid.** Een montage op muziek vergeeft geen drift. Drie
lessen die veel tijd kostten:
- Nooit de tijdlijn aaneenschuiven — dat verschoof elke snede met 116 ms.
- `-frames:v N`, nooit `-t <seconden>`, anders stapelt afrondingsdrift op.
- Het `overlay`-filter laat frames vallen, en niet elke keer evenveel: dezelfde invoer van 2361
  frames gaf 2354, 2348 en 2353. Elke filterketen met `overlay` eindigt daarom op `fps=` plus
  `-frames:v N` uit de EDL.

Resultaat, gemeten: 53 van 53 snedes binnen één frame, gemiddelde afwijking 0 ms, en EDL 2361
frames = render 2361 frames.

**Waarom er ijkpunten in de code staan.** De beeldanalyse is geijkt op 21 iPhone-clips (4K60
HEVC) in `projecten/test/`. Twee signalen moesten uit meting worden bijgesteld — `licht` als
beloning werkte niet omdat alle buitenopnames op 1.00 zaten, dus het werd `te_donker`, een straf
onder 120 lux. Bij drone- of GoPro-materiaal moet er opnieuw geijkt worden;
`engine/cve/analyze/kalibratie.py` is daarvoor de plek.

**Waarom ffmpeg, whisper en Chrome niet in de installer zitten.** Licenties en omvang. De
kant-en-klare ffmpeg-builds zijn bijna allemaal GPL en zouden BeatCut meetrekken; het
whisper-model is 1,5 GB en alleen voor ondertitels. Daardoor is een verse installatie 370 MB in
plaats van ruim 2 GB — de app haalt bij de eerste start zelf op wat ontbreekt.

**Cross-platform vanaf het begin**, ook al draait het nu alleen op de Mac. Geen `sips`,
`osascript` of `open`, alle paden via `engine/cve/paths.py`. Een Windows-installer kún je niet
op een Mac maken, vandaar de GitHub-workflow die bij een tag op drie runners tegelijk bouwt.

## Wat er nog open staat

1. **AI-titels die naar de beelden kijken** (± halve dag). De feitelijke titels — plaats, datum,
   hoogte — staan er. De volgende stap is een model dat per hoofdstuk een contactvel bekijkt en
   er iets persoonlijkers van maakt. Het feitelijke spoor blijft de standaard, want de
   werk-editie moet offline kunnen.
2. **Automatische updates** (1 uur of 1 dag). De app meldt nu alleen dát er een nieuwe versie is
   via de GitHub-releases-API. De Tauri-schil met handtekeningcontrole is de nette route; Rust
   1.97 staat al op deze Mac. Zie `installer/LEESMIJ.md`.
3. **Ondertekenen.** Zonder certificaat waarschuwt macOS ("ontwikkelaar niet geverifieerd") en
   Windows (SmartScreen). Voor eigen gebruik te doen; voor bredere uitrol de eerste uitgave die
   je moet doen.
4. GoPro GPMF en DJI SRT zijn in de telemetrielezer voorbereid maar niet geïmplementeerd.

## Handige plekken

- `OVERDRACHT.md` — waar we gebleven zijn, wat het eerstvolgende is, en de vier duurste mijnen.
- `CLAUDE.md` — de werkafspraken en de volledige stand van zaken per fase.
- `PLAN.md` — de architectuur.
- `installer/LEESMIJ.md` — de afweging tussen de goedkope updatecontrole en de Tauri-schil.
- Testproject `projecten/test/` — 21 iPhone-clips en één muziektrack; hierop is alles gemeten.
- `github.com/Koen-io/beatcut` (privé). `projecten/` staat er bewust buiten: video's zijn
  gebruikersdata. Installers gaan naar Releases, niet in git.

---

De technische uitleg voor een sessie staat in `CLAUDE.md`. Dit bestand herhaalt dat niet.
