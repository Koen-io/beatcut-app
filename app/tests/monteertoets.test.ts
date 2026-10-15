// node --test app/tests/monteertoets.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import { monteeractie, typtInVeld } from "../src/monteertoets.ts";

test("ongedaan en opnieuw op Mac en Windows", () => {
  assert.equal(monteeractie({ key: "z", metaKey: true }), "ongedaan");
  assert.equal(monteeractie({ key: "Z", metaKey: true, shiftKey: true }), "opnieuw");
  assert.equal(monteeractie({ key: "z", ctrlKey: true }), "ongedaan");
  assert.equal(monteeractie({ key: "y", ctrlKey: true }), "opnieuw");
  assert.equal(monteeractie({ key: "s", metaKey: true }), null, "⌘S is niet van ons");
});

test("knippen, weghalen, snede schuiven, shot kiezen", () => {
  assert.equal(monteeractie({ key: "s" }), "splits");
  assert.equal(monteeractie({ key: "S" }), "splits");
  assert.equal(monteeractie({ key: "Backspace" }), "verwijder");
  assert.equal(monteeractie({ key: "Delete" }), "verwijder");
  assert.equal(monteeractie({ key: "," }), "snede-terug");
  assert.equal(monteeractie({ key: "." }), "snede-vooruit");
  assert.equal(monteeractie({ key: "ArrowLeft", altKey: true }), "vorig-shot");
  assert.equal(monteeractie({ key: "ArrowRight", altKey: true }), "volgend-shot");
});

test("wat van de speler en de scrubbalk is blijft van hen", () => {
  assert.equal(monteeractie({ key: " " }), null);
  assert.equal(monteeractie({ key: "ArrowLeft" }), null);
  assert.equal(monteeractie({ key: "j" }), null);
});

test("typen in een veld gaat voor", () => {
  assert.equal(typtInVeld({ tagName: "INPUT" }), true);
  assert.equal(typtInVeld({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(typtInVeld({ tagName: "BUTTON" }), false);
  assert.equal(typtInVeld(null), false);
});
