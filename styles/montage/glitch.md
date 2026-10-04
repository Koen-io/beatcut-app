# Glitch

Snel en stotterend: twee korte snedes, dan één dubbele.

Het oneven patroon geeft het hikkende gevoel waar deze stijl om gaat.

```yaml montage
energie:        5
patroon:        1 1 2
overgangen:     snede glitch pixel slice rgb_split
overgang_elke:  2
overgang_duur:  0.2
ken_burns:      nee
ken_burns_kracht: 0.0
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Hoe de overgangen gemaakt worden

Glitch, pixel, slice en RGB-split wisselen elkaar af, om de twee snedes; ze lopen door de compositor en zijn in de voorvertoning precies zo te zien.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
