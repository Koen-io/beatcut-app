# Reis

Mengvorm, voor een mix van rustige en bewegende beelden.
Scherpte, licht en gezichten wegen hier allemaal mee zonder dat één signaal de
keuze overneemt. Hoe snel er gesneden wordt staat hier niet in — dat kies je
met de montagestijl (standaard `Cinematisch reizen`).

```yaml gewichten
beweging:          0.22
scherpte:          0.26
belichting:        0.18
shake:            -0.18
vlakheid:         -0.14
gezicht:           0.14   # reisvideo's gaan ook over de mensen
te_donker:        -0.30
geluid:            0.00
lengte_voorkeur:   0.10
consistentie:      0.38
```

```yaml ritme
min_shot:          1.5    # alleen de terugval als er geen muziek ligt
max_shot:          5.0    # informatief; de regisseur leest dit niet
drops:             sneller
opening_extra:     0.5    # nog niet gebouwd; niets leest dit
slot_extra:        1.0    # nog niet gebouwd; niets leest dit
```

## Beweging in het beeld

Alleen de echt stilstaande shots, en subtiel. In een reismontage wisselen
statief en handheld elkaar af; een te zware zoom valt dan op als een truc.

```yaml beweging
ken_burns:         ja
drempel:           0.12
min_duur:          2.0
kracht:            0.10
kracht_max:        0.16
```

```yaml kleur
contrast:          1.08
verzadiging:       1.12
warmte:            0.08
```

## Bijstellen

Voelt de drop te druk? Dat is de montagestijl, niet dit bestand: kies er een
met een rustiger patroon.
Wil je de mensen er meer in? Verhoog `gezicht` naar 0.25.
