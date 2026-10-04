# Cinematisch reizen

Eén shot per maat, met een zachte overvloei om de andere snede.

De rustigste van de middenmoot. Langzame Ken Burns van 4 % houdt het beeld levend zonder dat je het ziet.

```yaml montage
energie:        3
patroon:        4
overgangen:     snede crossfade
overgang_elke:  2
overgang_duur:  0.25
ken_burns:      ja
ken_burns_drempel: 0.3
ken_burns_kracht: 0.04
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Hoe de overgangen gemaakt worden

De overvloei is een echte crossfade met overlappende beelden (compositor).

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
