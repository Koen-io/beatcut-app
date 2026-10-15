// node --test app/tests/exportgeheugen.test.ts
//
// Van stap wisselen tijdens een export mocht de bestandsnaam en "toon als het
// klaar is" niet meer kwijtmaken (nalooprond 05-10, gerepareerd 13-10-2026).
import test from "node:test";
import assert from "node:assert/strict";

import {
  exportnaamVan,
  neemNaAfloop,
  onthoudExportnaam,
  onthoudNaAfloop,
  vergeetAlles,
} from "../src/exportgeheugen.ts";
import { heeftHandwerk, telHandwerk } from "../src/handwerk.ts";

test("de naam blijft per project bewaard, en een ander project krijgt hem niet", () => {
  vergeetAlles();
  onthoudExportnaam("vakantie", "Zomer 2026");
  assert.equal(exportnaamVan("vakantie"), "Zomer 2026");
  assert.equal(exportnaamVan("werk"), "");
  assert.equal(exportnaamVan(null), "");
  onthoudExportnaam("vakantie", "");
  assert.equal(exportnaamVan("vakantie"), "");
  onthoudExportnaam(null, "niets"); // mag niet knallen
});

test("toon-na-afloop gaat precies één keer af, en alleen voor dat project", () => {
  vergeetAlles();
  assert.equal(neemNaAfloop("vakantie"), null); // een render die al klaar lag
  onthoudNaAfloop("vakantie", { toon: true });
  assert.equal(neemNaAfloop("werk"), null);
  assert.deepEqual(neemNaAfloop("vakantie"), { toon: true });
  assert.equal(neemNaAfloop("vakantie"), null);
});

test("handwerk is elk shot dat vast staat", () => {
  assert.equal(heeftHandwerk([]), false);
  assert.equal(heeftHandwerk([{ vast: false }, { vast: false }]), false);
  assert.equal(telHandwerk([{ vast: true }, { vast: false }, { vast: true }]), 2);
  assert.equal(heeftHandwerk([{ vast: true }]), true);
});
