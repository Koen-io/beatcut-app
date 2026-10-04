# Velocity

Elke tel een snede, met een korte witte flits op de kick.

De snelste stijl die er is. Vijf snedes per vijf tellen, waarvan de laatste dubbel zo lang — dat geeft net genoeg lucht om het beeld te zien.

```yaml montage
energie:        5
patroon:        1 1 1 1 2
overgangen:     snede dip_wit zoom_punch
overgang_elke:  4
overgang_duur:  0.12
ken_burns:      nee
ken_burns_kracht: 0.0
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
ramp:           1.0 0.3 2.5
ramp_bij:       hoog
```

## Hoe de overgangen gemaakt worden

De speed-ramp 1,0→0,3→2,5x zit erin (shots vanaf 0,9 s op de drop). Om de vier snedes een witte flits of een zoom-punch.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
