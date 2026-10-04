# Verhaal

Lange overvloeiers en alles net iets langzamer dan echt.

Elk shot op 0,85x: dat haalt de haast eruit zonder dat het slowmotion wordt.

```yaml montage
energie:        2
patroon:        4 8
overgangen:     snede crossfade
overgang_elke:  2
overgang_duur:  0.5
ken_burns:      ja
ken_burns_drempel: 0.3
ken_burns_kracht: 0.06
snelheid:       0.85
snelheid_bij:   altijd
bevriezen:      0.0
bevriezen_bij:  geen
```

## Hoe de overgangen gemaakt worden

De overvloei van een halve seconde is een echte crossfade (compositor).

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
