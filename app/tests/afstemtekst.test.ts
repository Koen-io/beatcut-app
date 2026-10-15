// node --test app/tests/afstemtekst.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import { afstemTekst, redenTekst } from "../src/afstemtekst.ts";

test("de reden van de regisseur in de woorden van het scherm", () => {
  const labels = { vlakheid: "Detail", audiopiek: "Geluidspiek" };
  assert.equal(
    redenTekst("rustig: vlakheid -0.10, audiopiek +0.04 (score 0.27)", labels),
    "Rustig deel: detail -0,10, geluidspiek +0,04 (score 0,27)",
  );
  assert.equal(redenTekst("hoog: beweging +0.30 (score 0.70) · spraak", {}),
    "Drop: beweging +0,30 (score 0,70) · met spraak");
  assert.equal(redenTekst("door jou vastgezet", labels), "door jou vastgezet");
});

test("geen getallen is: past al", () => {
  assert.equal(afstemTekst(undefined), "Dit shot past al bij de rest.");
  assert.equal(afstemTekst({}), "Dit shot past al bij de rest.");
});

test("lichter, donkerder, warmer en koeler in gewone taal", () => {
  assert.equal(afstemTekst({ r: 1.25, g: 1.25, b: 1.25 }), "Dit shot wordt 25 % lichter.");
  assert.equal(afstemTekst({ r: 0.9, g: 0.9, b: 0.9 }), "Dit shot wordt 10 % donkerder.");
  assert.equal(afstemTekst({ r: 1.06, g: 1.0, b: 0.94 }), "Dit shot wordt warmer.");
  assert.equal(afstemTekst({ r: 1.1, g: 1.12, b: 1.2 }), "Dit shot wordt 12 % lichter en koeler.");
  assert.equal(afstemTekst({ r: 1.01, g: 1.0, b: 0.99 }), "Dit shot krijgt een kleine correctie.");
});
