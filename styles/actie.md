# Actie

Voor beelden met veel beweging en een bewegende camera: sport, rennen, rijden.
Beweging en scherpte wegen zwaar, lange rustige stukken vallen af. Hoe snel er
gesneden wordt staat hier niet in — dat kies je met de montagestijl
(standaard `Hype`).

```yaml gewichten
beweging:          0.30   # optical flow; actie is de kern
scherpte:          0.25   # onscherp valt af
belichting:        0.15   # spreiding in het histogram
shake:            -0.10   # licht negatief; wat schudden hoort bij actie
vlakheid:         -0.15   # lucht, muur, niets te zien
gezicht:           0.15   # uit camera-telemetrie, gratis
te_donker:        -0.30   # straf onder ~120 lux
geluid:            0.00   # zie hieronder - niet bruikbaar voor deze stijl
lengte_voorkeur:   0.06   # anders wint het kortste venster altijd
consistentie:      0.35   # hoe zwaar het slechtste moment meetelt
```

```yaml ritme
min_shot:          1.0    # alleen de terugval als er geen muziek ligt
max_shot:          4.0    # informatief; de regisseur leest dit niet
drops:             sneller
opening_extra:     0.0    # nog niet gebouwd; niets leest dit
slot_extra:        0.5    # nog niet gebouwd; niets leest dit
```

## Beweging in het beeld

Uit. De shots duren hier een tot vier seconden en zitten al vol beweging;
er nog een langzame zoom overheen leggen maakt het alleen maar onrustig.

```yaml beweging
ken_burns:         nee
```

```yaml kleur
contrast:          1.08
verzadiging:       1.12
warmte:            0.10
```

### Waarom `geluid` op nul staat

Stiltedetectie op -32 dB vindt bij buitenopnames vooral wind en verkeer, geen
spraak. Het signaal stond overal op 1.00 en onderscheidde dus niets. Bij een
pratende kop is het wel bruikbaar; dan hoort er een whisper-transcript onder.

### Waarom `licht` een straf werd en geen beloning

Eerste versie gaf punten voor meer lux. Alle buitenopnames kwamen op 1.00 uit
en de score werd er alleen maar platter van. Nu telt licht alleen mee als het
te donker is om iets te zien.

### Wanneer je deze stijl níét moet gebruiken

Bij natuur- en reisbeelden. `beweging` weegt hier zwaar en `lengte_voorkeur`
licht, dus de regisseur kiest juist de korte, drukke stukken. Een uitzicht dat
stilstaat scoort dan laag en haalt de montage niet. Neem `landschap` of `reis`.
