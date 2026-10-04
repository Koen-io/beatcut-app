# Reis FPV

Vliegend ritme: kort, twee keer langer, en weer kort.

Het patroon ademt mee met een vlucht: aanzet, doorvliegen, uitkomen.

```yaml montage
energie:        4
patroon:        1 2 2 1
overgangen:     snede whip_pan zoom_punch
overgang_elke:  3
overgang_duur:  0.25
ken_burns:      nee
ken_burns_kracht: 0.0
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
ramp:           1.0 0.4 2.0
ramp_bij:       hoog
```

## Hoe de overgangen gemaakt worden

Whip-pan en zoom-punch volgen de camerabeweging; de ramp zit in de shots op de drop.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
