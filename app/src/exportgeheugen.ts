// Wat het exportpaneel moet onthouden terwijl het niet getekend is.
//
// Exporteren is een stap; wie tijdens de export naar Bijwerken klikt en terug
// krijgt een vers getekend paneel. Daarmee was tot 13-10-2026 de ingetypte
// bestandsnaam weg, en "toon in Finder als het klaar is" ging niet af omdat
// niemand meer wist dat de export van hieruit gestart was. Dit woordenboek
// leeft zolang de app leeft — per project, zodat project B nooit de naam van
// A krijgt. Pure functies, getoetst in app/tests/exportgeheugen.test.ts.

export type NaAfloop = { toon: boolean };

const namen = new Map<string, string>();
const naAfloop = new Map<string, NaAfloop>();

/** De naam die voor dit project ingetypt stond, of leeg. */
export function exportnaamVan(project: string | null): string {
  return project === null ? "" : (namen.get(project) ?? "");
}

export function onthoudExportnaam(project: string | null, naam: string): void {
  if (project === null) return;
  if (naam === "") namen.delete(project);
  else namen.set(project, naam);
}

/** Bij het starten van een export: wat er moet gebeuren als hij klaar is. */
export function onthoudNaAfloop(project: string, wat: NaAfloop): void {
  naAfloop.set(project, wat);
}

/** Haal op én vergeet: "toon als het klaar is" mag precies één keer afgaan,
 *  en nooit voor een render die al klaar lag toen het paneel openging. */
export function neemNaAfloop(project: string): NaAfloop | null {
  const wat = naAfloop.get(project) ?? null;
  naAfloop.delete(project);
  return wat;
}

/** Voor tests. */
export function vergeetAlles(): void {
  namen.clear();
  naAfloop.clear();
}
