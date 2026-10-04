// Mag de export beginnen, of hoort er eerst een vraag?
//
// Dit staat apart van `Exporteren.tsx` omdat het precies de soort beslissing
// is die stil fout gaat: twee antwoorden die nog onderweg zijn, allebei met
// `null` als beginwaarde, en `null` dat per ongeluk "er is niets aan de hand"
// betekent. Daardoor kon een klik vlak na het openen van de stap een export
// zonder titels starten zonder dat er iets gevraagd werd.
//
// Hier wordt "nog niet bekend" en "niet gelukt" dus los van "gecontroleerd"
// gehouden, en een niet-gelukte controle telt nooit als "er zijn geen titels".

/** Hoeveel titels er in de montage staan — als we dat al weten. */
export type Titelstand =
  | { soort: "onbekend" }                 // de vraag loopt nog
  | { soort: "mislukt" }                  // de vraag faalde; er kunnen titels zijn
  | { soort: "aantal"; aantal: number };

/** Of de titelmotor (node, HyperFrames, browser) klaarstaat. */
export type Motorstand = "onbekend" | "klaar" | "mist";

export type Exportoordeel =
  | "wacht"   // de controles lopen nog; de knop hoort uit te staan
  | "vraag"   // er kunnen titels wegvallen; eerst bevestigen
  | "ga";

/**
 * Leid de stand van de titelmotor af uit wat `useOnderdelen` weet.
 *
 * Een statusvraag die mislukt blijft `null`, en dan zou de knop voor altijd
 * uit staan. Daarom telt een mislukte controle als "mist": we weten het niet,
 * dus we vragen het liever één keer te veel.
 */
export function motorstand(
  status: { alles_klaar: boolean } | null,
  standsoort: string,
): Motorstand {
  if (status !== null) return status.alles_klaar ? "klaar" : "mist";
  return standsoort === "fout" ? "mist" : "onbekend";
}

export function exportOordeel(titels: Titelstand, motor: Motorstand): Exportoordeel {
  if (motor === "onbekend" || titels.soort === "onbekend") return "wacht";
  if (motor === "klaar") return "ga";
  // De motor mist. Alleen bij een gecontroleerde nul titels valt er niets te
  // melden; "mislukt" telt nadrukkelijk níet als nul.
  return titels.soort === "aantal" && titels.aantal === 0 ? "ga" : "vraag";
}
