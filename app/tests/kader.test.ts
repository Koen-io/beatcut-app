// node --test app/tests/kader.test.ts  (Node 24 leest TypeScript zelf)
//
// De speler-kant van het herkaderen, tegen dezelfde tabel getallen als
// tests/test_kader.py. Loopt een van de twee weg, dan laat de voorvertoning
// iets anders zien dan de export maakt — en dan is het shot dat je goedkeurde
// niet het shot dat in de video komt.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { kaderPas, kaderPuntOp, kaderVul, schuif, venster } from "../src/speler/kader.ts";

const tabel = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../tests/kader-gevallen.json", import.meta.url)), "utf-8"),
) as {
  gevallen: {
    naam: string;
    bronverhouding: number;
    canvasverhouding: number;
    zoom: number;
    panX: number;
    panY: number;
    kaderX: number;
    kaderY: number;
    verwacht: { schaalX: number; schaalY: number; schuifX: number; schuifY: number };
  }[];
};

for (const g of tabel.gevallen) {
  test(`kaderVul — ${g.naam}`, () => {
    const k = kaderVul(g.bronverhouding, g.canvasverhouding, g.zoom, g.panX, g.panY, g.kaderX, g.kaderY);
    for (const veld of ["schaalX", "schaalY", "schuifX", "schuifY"] as const) {
      assert.ok(
        Math.abs(k[veld] - g.verwacht[veld]) < 1e-6,
        `${veld}: ${k[veld]} ≠ ${g.verwacht[veld]}`,
      );
    }
  });
}

test("zonder kaderpunt is kaderVul precies wat hij was: gecentreerd", () => {
  const met = kaderVul(16 / 9, 9 / 16, 1.2, 0.4, 0, 0.5, 0.5);
  const zonder = kaderVul(16 / 9, 9 / 16, 1.2, 0.4, 0);
  assert.deepEqual(met, zonder);
});

test("het venster blijft binnen de bron", () => {
  const [b] = venster(16 / 9, 9 / 16);
  assert.equal(schuif(b, 0), 0);
  assert.ok(Math.abs(schuif(b, 1) - (1 - b)) < 1e-9);
  assert.equal(schuif(1, 0.2), 0); // geen ruimte = geen schuif
});

test("keyframes lopen lineair en schieten niet door", () => {
  const k = { punten: [{ t: 0, x: 0.2, y: 0.5 }, { t: 1, x: 0.8, y: 0.5 }] };
  assert.ok(Math.abs(kaderPuntOp(k, 0)[0] - 0.2) < 1e-9);
  assert.ok(Math.abs(kaderPuntOp(k, 0.5)[0] - 0.5) < 1e-9);
  assert.ok(Math.abs(kaderPuntOp(k, 2)[0] - 0.8) < 1e-9);
  assert.deepEqual(kaderPuntOp(undefined), [0.5, 0.5]);
  assert.deepEqual(kaderPuntOp({ x: 0.3, y: 0.7 }), [0.3, 0.7]);
});

test("kaderPas raakt het kader niet aan — balken blijven gecentreerd", () => {
  // `pas` en `wazig` passen het hele beeld in; daar valt niets weg te snijden
  // en dus ook niets te herkaderen.
  const k = kaderPas(16 / 9, 9 / 16);
  assert.ok(Math.abs(k.schuifY - (1 - k.schaalY) / 2) < 1e-9);
});
