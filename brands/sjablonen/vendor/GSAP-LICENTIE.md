# GSAP 3.14.2 — waarom dit bestand hier staat

`gsap.min.js` komt uit het npm-pakket `gsap@3.14.2` (via jsDelivr, 03-10-2026).
Het is hier meegeleverd omdat een render **nooit het internet nodig mag hebben**
(CLAUDE.md regel 5: de werk-editie draait volledig offline). Eerder haalde
`brands/sjablonen/titel.html` het bij elke render van een CDN.

## Licentie

Het npm-pakket bevat zelf geen licentiebestand. GreenSock levert GSAP onder de
"standard no-charge license": <https://gsap.com/standard-license>. De kern en
alle plugins zijn gratis te gebruiken, inclusief in commercieel werk.

De enige beperking die ons zou kunnen raken: je mag GSAP niet gebruiken in een
product dat concurreert met de animatiebouwer van Webflow (eigenaar van
GreenSock). Een video-editor valt daar naar ons oordeel buiten — dat is een
inschatting, niet een juridisch advies. Zie `projectgeheugen/stijlen-looks-titels.md`.
