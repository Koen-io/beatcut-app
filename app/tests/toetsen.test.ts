// node --test app/tests/toetsen.test.ts
//
// De scrubbalk was tot 13-10-2026 alleen met de muis te bedienen. Dit legt
// vast wat elke toets doet, en dat niets buiten de video kan vallen.
import test from "node:test";
import assert from "node:assert/strict";

import { scrubSprong } from "../src/speler/toetsen.ts";

const bijna = (a: number | null, b: number) => {
  assert.ok(a !== null, "verwacht een tijd, kreeg null");
  assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`);
};

test("pijltjes stappen één frame, met Shift één seconde", () => {
  bijna(scrubSprong("ArrowRight", false, 25, 10, 2), 2 + 1 / 25);
  bijna(scrubSprong("ArrowLeft", false, 25, 10, 2), 2 - 1 / 25);
  bijna(scrubSprong("ArrowRight", true, 25, 10, 2), 3);
  bijna(scrubSprong("ArrowLeft", true, 25, 10, 2), 1);
});

test("Home, End, J en L", () => {
  bijna(scrubSprong("Home", false, 25, 10, 7), 0);
  bijna(scrubSprong("End", false, 25, 10, 7), 10);
  bijna(scrubSprong("j", false, 25, 10, 7), 6);
  bijna(scrubSprong("L", false, 25, 10, 7), 8);
});

test("nooit buiten de video, ook niet bij een onbekende fps", () => {
  bijna(scrubSprong("ArrowLeft", true, 25, 10, 0.2), 0);
  bijna(scrubSprong("ArrowRight", true, 25, 10, 9.9), 10);
  bijna(scrubSprong("ArrowRight", false, 0, 10, 0), 1 / 30);
});

test("andere toetsen en een lege video zijn niet van ons", () => {
  assert.equal(scrubSprong("a", false, 25, 10, 2), null);
  assert.equal(scrubSprong("ArrowRight", false, 25, 0, 0), null);
});
