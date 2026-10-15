// Wat de onderbalk van een voortgangsmelding maakt: hoe vol de balk staat en
// wat er in woorden bij komt. Apart van Media.tsx omdat dit de twee dingen
// zijn die Koen moet kunnen vertrouwen, en een los bestand is te testen.
//
// De rekenkunde zit in de engine (`engine/cve/doorvoer.py`); hier gaat het
// alleen over het gat tussen twee meldingen en over de woorden.
import { duurTekst, ongeveerTekst } from "./format.ts";
import type { Voortgang } from "./engine.ts";

/** Hoe vol de balk staat, als breuk — of null als het onbekend is (dan hoort
 *  de balk te pendelen in plaats van een stand te suggereren).
 *
 *  De engine weegt naar tijd en niet naar bronvideo: een balk op bronvideo zit
 *  vast tijdens het inlezen en schiet vooruit tijdens het analyseren, want de
 *  ene seconde bronvideo kost daar tien keer zoveel als de andere. `sinds`
 *  schuift de balk tussen twee meldingen verder, zodat hij vloeiend loopt in
 *  plaats van per clip te verspringen. */
export function balkDeel(vg: Voortgang | null, sinds: number): number | null {
  if (vg === null) return null;
  if (vg.aandeel != null) {
    if (vg.resterend == null || vg.aandeel >= 1) return vg.aandeel;
    // De engine geeft breuk en resterende tijd uit één som, dus de totale duur
    // is eruit terug te rekenen — en daarmee hoeveel breuk een seconde is.
    return Math.min(1, vg.aandeel + sinds / (vg.resterend / (1 - vg.aandeel)));
  }
  return vg.totaal > 0 ? vg.gedaan / vg.totaal : null;
}

/** "1:05 verstreken · nog ±0:40". Null zolang er geen klok meeloopt.
 *
 *  `schat` is het verschil tussen "de engine meet nog en weet het niet"
 *  (→ schatten…) en "dit soort werk schat helemaal niet" (→ alleen verstreken).
 *  Zonder dat onderscheid staat er "bijna klaar" op het moment dat er nog
 *  niets gemeten is. */
export function tijdenTekst(
  verstreken: number | null,
  schat: boolean,
  resterend: number | null,
): string | null {
  if (verstreken === null) return null;
  const links = `${duurTekst(verstreken)} verstreken`;
  if (!schat) return links;
  if (resterend === null) return `${links} · nog even schatten…`;
  // Onder de acht seconden is elk getal een slag in de lucht, en "nog ±0:05"
  // dat drie keer blijft staan leest slechter dan dit.
  if (resterend < 8) return `${links} · bijna klaar`;
  return `${links} · nog ±${ongeveerTekst(resterend)}`;
}
