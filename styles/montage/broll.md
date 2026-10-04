# B-roll ritme

Snelle reeksen detailbeelden, en dan even rust.

Vier korte shots gevolgd door één lange maat. Dat wisselen is precies waar een b-roll-reeks van leeft.

```yaml montage
energie:        4
patroon:        1 2 1 2 4
overgangen:     snede
overgang_elke:  0
overgang_duur:  0.0
ken_burns:      nee
ken_burns_kracht: 0.0
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Wat de renderer hier nog niet kan

J/L-cuts (geluid dat eerder begint of doorloopt) kan de EDL wel, maar de regisseur zet ze nog niet; dat hangt aan de compositor.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
