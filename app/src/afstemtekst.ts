// De kleurafstemming van één shot in gewone taal. "×1,25 ×1,25 ×1,25" zegt
// een colorist iets; "een kwart lichter" zegt iedereen iets. Pure functie,
// getoetst in app/tests/afstemtekst.test.ts.

type Kleur = { r?: number; g?: number; b?: number } | undefined;

/** De `reden` van de regisseur ("rustig: vlakheid -0.10, audiopiek +0.04
 *  (score 0.27)") in de woorden van het scherm: de labels van "Waarom dit
 *  shot", komma's in plaats van punten. `labels` is naam → label. */
export function redenTekst(reden: string, labels: Record<string, string>): string {
  const niveaus: Record<string, string> = {
    rustig: "Rustig deel",
    opbouw: "Opbouw",
    hoog: "Drop",
    midden: "Midden",
  };
  let t = reden.replace(/^(\w+):/, (_, n: string) => `${niveaus[n] ?? n}:`);
  t = t.replace(/\b([a-z_]+) ([+-]\d+\.\d+)/g, (_, naam: string, getal: string) =>
    `${(labels[naam] ?? naam).toLowerCase()} ${getal.replace(".", ",")}`);
  t = t.replace(/\(score (\d+)\.(\d+)\)/, "(score $1,$2)");
  return t.replace(/ · spraak$/, " · met spraak");
}

export function afstemTekst(k: Kleur): string {
  if (!k || Object.keys(k).length === 0) return "Dit shot past al bij de rest.";
  const r = k.r ?? 1;
  const g = k.g ?? 1;
  const b = k.b ?? 1;
  const licht = (0.2126 * r + 0.7152 * g + 0.0722 * b - 1) * 100;
  const delen: string[] = [];
  if (Math.abs(licht) >= 3) {
    delen.push(`${Math.round(Math.abs(licht))} % ${licht > 0 ? "lichter" : "donkerder"}`);
  }
  const warmte = r - b;
  if (Math.abs(warmte) >= 0.04) delen.push(warmte > 0 ? "warmer" : "koeler");
  if (delen.length === 0) return "Dit shot krijgt een kleine correctie.";
  return `Dit shot wordt ${delen.join(" en ")}.`;
}
