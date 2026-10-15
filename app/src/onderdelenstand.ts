// Welke stand hoort bij een 'fout'-melding van het klaarzetten, los van React
// zodat het te testen is.
import type { OnderdelenStand } from "./onderdelen";

/** De engine meldt zelf stoppen ook als 'fout', met soort 'Gestopt'
 *  (engine/cve/onderdelen.py). Dat is geen storing: de titels staan gewoon nog
 *  niet klaar, en zo leest het dan ook — "Nu ophalen", niet "Opnieuw proberen". */
export function standNaFout(data: { fout: string; soort: string }): OnderdelenStand {
  if (data.soort === "Gestopt") return { soort: "mist" };
  return { soort: "fout", bericht: data.fout };
}
