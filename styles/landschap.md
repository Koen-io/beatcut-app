# Landschap

Voor natuur, uitzichten en reisbeelden zonder mensen in beeld.
Scherpte, mooi licht en lange rustige segmenten wegen zwaar; wiebelen valt af.
Hoe lang een shot in de montage duurt staat hier niet in — dat kies je met de
montagestijl (standaard `Ambient`).

```yaml gewichten
beweging:          0.12   # beweging is niet het doel; te veel = onrustig
scherpte:          0.30   # scherpte is hier het belangrijkst
belichting:        0.22   # mooi licht maakt een landschap
shake:            -0.30   # wiebelen is dodelijk bij lange shots
vlakheid:         -0.10   # een lege lucht mag, als de rest klopt
gezicht:           0.05
te_donker:        -0.30
geluid:            0.00
lengte_voorkeur:   0.16   # duidelijke voorkeur voor lange segmenten
consistentie:      0.45   # over 5 seconden mag niets wegzakken
```

```yaml ritme
min_shot:          3.0    # alleen de terugval als er geen muziek ligt
max_shot:          6.5    # informatief; de regisseur leest dit niet
drops:             beeld
opening_extra:     1.0    # nog niet gebouwd; niets leest dit
slot_extra:        1.5    # nog niet gebouwd; niets leest dit
```

## Beweging in het beeld

Landschappen komen vaak van een statief of een rustige hand. Zonder een
trage duw voelt zo'n shot van vijf seconden als een foto. De drempel ligt hier
hoger dan standaard: ook een licht bewegend shot mag een zetje krijgen.

```yaml beweging
ken_burns:         ja
drempel:           0.18
min_duur:          2.0
kracht:            0.10
kracht_max:        0.20
```

```yaml kleur
contrast:          1.06
verzadiging:       1.10
warmte:            0.06
```

## Waarom `drops: beeld`

`drops: beeld` geeft de beeldscore in een drop een flinke bonus, zodat de
hoogstscorende shots precies daar terechtkomen. De energie komt dus uit de
beeldkeuze. Het tempo blijft wat de montagestijl zegt — en dat is wat je wilt
bij landschap, waar snel snijden het onderwerp juist onzichtbaar maakt.

## Bijstellen

Nog te snel? Dat zit niet in dit bestand: kies een rustiger montagestijl
(`Ambient`, `Stilte`, `Cinematisch reizen`).
Te statisch? Verhoog `beweging` naar 0.20.
