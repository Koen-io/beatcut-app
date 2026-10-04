# Vlog

Op de maat, met af en toe een halve maat ertussen.

Ruimte om iemand te laten uitpraten, maar niet zo lang dat het stilvalt. Stilstaande shots krijgen een inzoom die de sprong verbergt.

```yaml montage
energie:        3
patroon:        4 2 4
overgangen:     snede
overgang_elke:  0
overgang_duur:  0.0
ken_burns:      ja
ken_burns_drempel: 0.2
ken_burns_kracht: 0.1
snelheid:       1.0
snelheid_bij:   geen
bevriezen:      0.0
bevriezen_bij:  geen
```

## Wat de renderer hier nog niet kan

Snijden op de spraak zelf (in plaats van op de maat) vraagt woordgrenzen uit whisper; die staan er wel, maar de regisseur gebruikt ze nog niet.

## Bijstellen

`patroon` staat in tellen; vier tellen is een maat. Meer getallen betekent een
afwisselender ritme. `overgang_elke` is om de hoeveel snedes de tweede naam uit
`overgangen` gebruikt wordt; 0 betekent nooit.
