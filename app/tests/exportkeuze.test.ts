// node --test app/tests/exportkeuze.test.ts  (Node 24 leest TypeScript zelf)
import test from "node:test";
import assert from "node:assert/strict";

import { exportOordeel, motorstand } from "../src/exportkeuze.ts";

test("zolang een van de twee controles loopt, mag de export niet beginnen", () => {
  assert.equal(exportOordeel({ soort: "onbekend" }, "klaar"), "wacht");
  assert.equal(exportOordeel({ soort: "aantal", aantal: 0 }, "onbekend"), "wacht");
  assert.equal(exportOordeel({ soort: "onbekend" }, "onbekend"), "wacht");
});

test("een mislukte montagevraag telt niet als nul titels", () => {
  // Dit was de fout: `montage?.titels.length ?? 0` maakte van een mislukte
  // vraag stilletjes "geen titels", en dan bleef de waarschuwing weg.
  assert.equal(exportOordeel({ soort: "mislukt" }, "mist"), "vraag");
  assert.equal(exportOordeel({ soort: "mislukt" }, "klaar"), "ga");
});

test("gecontroleerd en in orde: gewoon exporteren", () => {
  assert.equal(exportOordeel({ soort: "aantal", aantal: 3 }, "klaar"), "ga");
  assert.equal(exportOordeel({ soort: "aantal", aantal: 0 }, "mist"), "ga");
});

test("titels én een motor die mist: eerst vragen", () => {
  assert.equal(exportOordeel({ soort: "aantal", aantal: 1 }, "mist"), "vraag");
});

test("een statusvraag die mislukte zet de knop niet voorgoed vast", () => {
  assert.equal(motorstand(null, "fout"), "mist");
  assert.equal(motorstand(null, "kijken"), "onbekend");
  assert.equal(motorstand({ alles_klaar: true }, "kijken"), "klaar");
  assert.equal(motorstand({ alles_klaar: false }, "bezig"), "mist");
});
