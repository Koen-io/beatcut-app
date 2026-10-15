// De naam van de app, voor modules zonder afhankelijkheden (die draaien ook
// onder `node --test`, waar de Vite-alias `@editie` niet bestaat).
// `editie.ts` zet hem bij het laden van de interface; in tests blijft het
// de standaard.
export let APP_NAAM = "BeatCut";

export function zetAppNaam(naam: string): void {
  APP_NAAM = naam;
}
