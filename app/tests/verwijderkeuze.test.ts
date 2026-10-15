// node --test app/tests/verwijderkeuze.test.ts  (Node 24 leest TypeScript zelf)
import test from "node:test";
import assert from "node:assert/strict";

import {
  STANDAARD,
  blijft,
  gaatWeg,
  grootteTekst,
  kopieGrootte,
  kopieNaam,
  kruimelpad,
  wegLijst,
  type Omvang,
} from "../src/verwijderkeuze.ts";

const omvang: Omvang = {
  naam: "test",
  aantal_clips: 21,
  soorten: {
    werk: { bytes: 726_000_000, bestanden: 90 },
    kopieen: { bytes: 2_100_000_000, bestanden: 21 },
    muziek: { bytes: 8_000_000, bestanden: 1 },
    exports: { bytes: 142_000_000, bestanden: 2 },
  },
  totaal: 2_976_000_000,
  kopie: { basis: 8_400_000, proxies: 341_000_000 },
  bezig: null,
  prullenbak: "Prullenmand",
  bewaard: "/Users/x/Movies/BeatCut/_Bewaard/test",
};

test("standaard blijven de geëxporteerde video's staan", () => {
  assert.deepEqual(wegLijst(STANDAARD), ["kopieen", "muziek"]);
  assert.equal(blijft(omvang, STANDAARD), 142_000_000);
});

test("het project zelf gaat altijd weg, ook als je alles houdt", () => {
  const niets = { kopieen: false, muziek: false, exports: false };
  assert.deepEqual(wegLijst(niets), []);
  assert.equal(gaatWeg(omvang, niets), 726_000_000);
});

test("weg en blijft zijn samen altijd het gemeten totaal", () => {
  for (const kopieen of [true, false])
    for (const muziek of [true, false])
      for (const exports of [true, false]) {
        const k = { kopieen, muziek, exports };
        assert.equal(gaatWeg(omvang, k) + blijft(omvang, k), omvang.totaal);
      }
});

test("een kleine montage is niet '0 MB'", () => {
  assert.equal(grootteTekst(0), "leeg");
  assert.equal(grootteTekst(400), "< 1 kB");
  assert.equal(grootteTekst(40_000), "40 kB");
  assert.equal(grootteTekst(8_400_000), "8,4 MB");
  assert.equal(grootteTekst(341_000_000), "341 MB");
  assert.equal(grootteTekst(2_834_000_000), "2,8 GB");
});

test("de kopie wordt alleen groter als de voorvertoningen meegaan", () => {
  assert.equal(kopieGrootte(omvang, false), 8_400_000);
  assert.equal(kopieGrootte(omvang, true), 349_400_000);
});

test("de voorgestelde naam van de kopie draagt project en datum", () => {
  assert.equal(kopieNaam("test", new Date(2026, 9, 4)), "test (BeatCut-kopie 2026-10-04).zip");
});

test("het kruimelpad werkt met beide scheidingstekens", () => {
  assert.equal(kruimelpad("/Users/x/Movies/BeatCut/_Bewaard/test"), "BeatCut › _Bewaard › test");
  assert.equal(kruimelpad("C:\\Users\\x\\Videos\\BeatCut\\_Bewaard\\test"), "BeatCut › _Bewaard › test");
});
