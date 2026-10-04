# Retro film

Eén shot per maat, met af en toe een lichtlek.

Rustig gesneden, want de korrel en de beeldtrilling doen het werk. Die zet je bij de Look-stap aan.

```yaml montage
energie:        2
patroon:        4
overgangen:     snede film_brand lichtlek
overgang_elke:  4
overgang_duur:  0.4
ken_burns:      ja
ken_burns_drempel: 0.28
ken_burns_kracht: 0.05
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Hoe de overgangen gemaakt worden

Filmbrand en lichtlek wisselen elkaar af als overgang. Korrel en trilling zitten in de afwerking van de Look-stap.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
