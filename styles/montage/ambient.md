# Ambient

Vier maten per shot, elke snede een lange overvloei.

De langzaamste stijl: een snede per muzikale frase. Het beeld drijft meer dan dat het beweegt.

```yaml montage
energie:        1
patroon:        16
overgangen:     crossfade
overgang_elke:  1
overgang_duur:  0.8
ken_burns:      ja
ken_burns_drempel: 0.35
ken_burns_kracht: 0.03
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Hoe de overgangen gemaakt worden

De lange overvloei is een echte crossfade met overlappende beelden, gemengd in licht.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
