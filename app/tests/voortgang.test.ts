// node --test app/tests/voortgang.test.ts  (Node 24 leest TypeScript zelf)
//
// De onderbalk van stap 1 is wat Koen in de gaten houdt terwijl 21 clips van
// 4K60 verwerkt worden. De rekenkunde erachter staat in de engine en wordt
// daar getest (tests/test_doorvoer.py); dit gaat over wat er op het scherm
// komt te staan — en vooral over de gevallen waarin er nog niets te zeggen is.
import test from "node:test";
import assert from "node:assert/strict";

import { balkDeel, tijdenTekst } from "../src/voortgang.ts";
import type { Voortgang } from "../src/engine.ts";

function melding(extra: Partial<Voortgang> = {}): Voortgang {
  return {
    werk: "verwerk",
    project: "test",
    stap: "inlezen",
    gedaan: 0,
    totaal: 0,
    tekst: "Beelden inlezen…",
    ...extra,
  };
}

// ---------------------------------------------------------------- de balk

test("zonder melding is er geen stand, en dus geen balk om te vullen", () => {
  assert.equal(balkDeel(null, 0), null);
});

test("zonder stand van de engine valt de balk terug op de bestandsteller", () => {
  // Niet mooi, maar beter dan niets: muziekgen en de installers tellen stuks.
  assert.equal(balkDeel(melding({ gedaan: 3, totaal: 12 }), 0), 0.25);
  assert.equal(balkDeel(melding({ gedaan: 0, totaal: 0 }), 0), null);
});

test("de balk schuift tussen twee meldingen gewoon door", () => {
  // Op 50 % met 20 s te gaan is de hele klus 40 s; vier seconden later hoort
  // de balk dus op 60 % te staan en niet nog steeds op 50 %. Zonder dit
  // verspringt hij per clip, en bij een lange 4K-opname staat hij een halve
  // minuut stil.
  const vg = melding({ aandeel: 0.5, resterend: 20 });
  assert.equal(balkDeel(vg, 0), 0.5);
  assert.equal(balkDeel(vg, 4), 0.6);
  // En hij loopt nooit voorbij vol, ook niet als de engine stil is gevallen.
  assert.equal(balkDeel(vg, 999), 1);
});

test("een volle balk blijft vol staan", () => {
  assert.equal(balkDeel(melding({ aandeel: 1, resterend: 0 }), 5), 1);
});

test("zonder tijdschatting staat de balk waar de engine hem zet", () => {
  // `resterend: null` = de engine meet nog. Dan is er geen totale duur om de
  // balk mee verder te schuiven, dus hij blijft staan tot de volgende melding.
  assert.equal(balkDeel(melding({ aandeel: 0.4, resterend: null }), 5), 0.4);
});

// --------------------------------------------------------------- de tekst

test("zonder klok staat er niets", () => {
  assert.equal(tijdenTekst(null, true, null), null);
});

test("werk dat niet schat toont alleen wat er verstreken is", () => {
  assert.equal(tijdenTekst(65, false, null), "1:05 verstreken");
});

test('nog niets gemeten wordt "schatten", geen getal', () => {
  // Koens eis: toon pas een getal na voldoende meting. "bijna klaar" of
  // "nog ±0:00" zou hier een belofte zijn die nergens op rust.
  assert.equal(tijdenTekst(12, true, null), "0:12 verstreken · nog even schatten…");
});

test("een schatting komt erbij, afgerond zodat hij niet per tel wisselt", () => {
  assert.equal(tijdenTekst(65, true, 42), "1:05 verstreken · nog ±0:40");
  assert.equal(tijdenTekst(65, true, 44), "1:05 verstreken · nog ±0:45");
  // Boven de minuut in stappen van tien.
  assert.equal(tijdenTekst(5, true, 184), "0:05 verstreken · nog ±3:00");
  assert.equal(tijdenTekst(5, true, 186), "0:05 verstreken · nog ±3:10");
});

test("de laatste seconden zijn woorden, geen getal", () => {
  assert.equal(tijdenTekst(30, true, 3), "0:30 verstreken · bijna klaar");
  assert.equal(tijdenTekst(30, true, 0), "0:30 verstreken · bijna klaar");
});
