# Beatflits

Om de twee tellen een snede, elke keer met een flits naar wit.

Het regelmatigste snelle ritme. In de drop bevriest het laatste stukje van elk shot — daar hoort de titel.

```yaml montage
energie:        4
patroon:        2
overgangen:     snede dip_wit
overgang_elke:  1
overgang_duur:  0.1
ken_burns:      nee
ken_burns_kracht: 0.0
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.25
bevriezen_bij:  hoog
```

## Hoe de overgangen gemaakt worden

De flits is een echte lichtflits uit de compositor, met dezelfde shader als de voorvertoning.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
