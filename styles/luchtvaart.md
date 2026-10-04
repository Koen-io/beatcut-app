# Luchtvaart

Voor beelden vanuit de helikopter: cameraopnames en FLIR/warmtebeeld.
De keuze gaat naar lange, volgbare segmenten zonder trillingen, want de kijker
moet het onderwerp kunnen volgen. Camerabeweging is hier geen fout maar de kern
van het beeld. Hoe lang een shot in de montage duurt kies je met de
montagestijl (standaard `Cinematisch reizen`).

**Nog niet geijkt op echt materiaal.** De onderstaande waarden zijn beredeneerd,
niet gemeten. Zie onderaan wat er moet gebeuren zodra er FLIR-beelden zijn.

```yaml gewichten
beweging:          0.16   # laag: bij lange lens is elke beweging al groot
scherpte:          0.14   # laag, zie de opmerking over FLIR hieronder
belichting:        0.10
shake:            -0.34   # zwaar: trillingen zijn hier het echte probleem
vlakheid:         -0.04   # bijna uit: lucht en zee zijn nu eenmaal vlak
gezicht:           0.02
te_donker:        -0.10   # nachtvluchten zijn donker en dat hoort zo
geluid:            0.00
lengte_voorkeur:   0.20   # sterke voorkeur voor lange, volgbare shots
consistentie:      0.50   # het onderwerp moet het hele shot in beeld blijven
```

```yaml ritme
min_shot:          4.0    # alleen de terugval als er geen muziek ligt
max_shot:          9.0    # informatief; de regisseur leest dit niet
drops:             beeld
opening_extra:     1.5    # nog niet gebouwd; niets leest dit
slot_extra:        2.0    # nog niet gebouwd; niets leest dit
```

## Beweging in het beeld

Zuinig. Beelden uit de lucht bewegen meestal vanzelf. Wat wél stilstaat -
een vaste FLIR-opname bijvoorbeeld - duurt hier lang genoeg om er baat bij te
hebben, maar de duw blijft klein: uitvergroten kost detail dat er toch al
weinig is.

```yaml beweging
ken_burns:         ja
drempel:           0.10
min_duur:          3.0
kracht:            0.08
kracht_max:        0.14
```

```yaml kleur
contrast:          1.04
verzadiging:       1.00
warmte:            0.00
```

## Waarom deze waarden afwijken

**`scherpte` staat laag en `vlakheid` bijna uit.** De ijkpunten in
`engine/cve/analyze/kalibratie.py` zijn gemeten op iPhone-beelden: een
Laplaciaan-variantie van 250 telt als onscherp, 6500 als scherp. FLIR-beelden
zijn van nature glad en contrastarm en zouden op die schaal allemaal als
onscherp scoren, ook als ze perfect zijn. Zolang die ijking niet apart is
gedaan, mag scherpte hier niet zwaar wegen. Hetzelfde geldt voor vlakheid:
lucht, zee en akkers zijn terecht vlak.

**`shake` weegt juist zwaar.** Een helikopter trilt. Bij een lange lens is dat
het verschil tussen bruikbaar en onbruikbaar, en het is wél betrouwbaar te
meten — het is een verschilmeting en dus ongevoelig voor de absolute schaal.

**`te_donker` weegt licht.** Nachtvluchten horen donker te zijn.

## Wat er moet gebeuren bij echt materiaal

1. Zet een handvol FLIR-clips en een handvol camera-clips in een testproject
2. Draai `cve analyse` en kijk naar de ruwe spreiding van de metingen
3. Maak een tweede ijkprofiel in `kalibratie.py` (bijvoorbeeld `flir`) en laat
   `cve analyse --kalibratie flir` dat gebruiken

Zonder die stap is deze stijl een beredeneerde gok, geen meting.
