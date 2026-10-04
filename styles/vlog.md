# Vlog

Voor beelden met veel gezichten en gesproken woord.
Mensen en gezichten tellen zwaarder mee, beweging juist minder — een pratend
hoofd staat nu eenmaal stil. Het tempo staat hier niet in; dat kies je met de
montagestijl (standaard `Vlog`).

```yaml gewichten
beweging:          0.20
scherpte:          0.24
belichting:        0.16
shake:            -0.14
vlakheid:         -0.16
gezicht:           0.28   # de vlog gaat over wie er in beeld is
te_donker:        -0.30
geluid:            0.05   # ruwe indicatie dat er iets gebeurt
lengte_voorkeur:   0.08
consistentie:      0.35
```

```yaml ritme
min_shot:          2.0    # alleen de terugval als er geen muziek ligt
max_shot:          4.0    # informatief; de regisseur leest dit niet
drops:             sneller
opening_extra:     0.5    # nog niet gebouwd; niets leest dit
slot_extra:        1.0    # nog niet gebouwd; niets leest dit
```

## Beweging in het beeld

Terughoudend. Een vlog draait om wat er gezegd wordt; een bewegend beeld
onder een pratend hoofd leidt af. Alleen de shots die echt stokstijf staan.

```yaml beweging
ken_burns:         ja
drempel:           0.08
min_duur:          2.5
kracht:            0.08
kracht_max:        0.12
```

```yaml kleur
contrast:          1.08
verzadiging:       1.10
warmte:            0.10
```
