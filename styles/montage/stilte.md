# Stilte

Twee maten per shot, en om de drie snedes een dip naar zwart.

Zo lang dat je het beeld echt bekijkt. Geen snelheidstrucs, geen flitsen.

```yaml montage
energie:        1
patroon:        8
overgangen:     snede dip_zwart
overgang_elke:  3
overgang_duur:  0.6
ken_burns:      ja
ken_burns_drempel: 0.35
ken_burns_kracht: 0.04
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Wat de renderer hier nog niet kan

Niets. Deze stijl gebruikt alleen wat de renderer vandaag al kan.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
