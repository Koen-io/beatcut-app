import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AFTEL_MS,
  INTERVAL_MS,
  deel,
  foutTekst,
  laatstTekst,
  sluitVanzelf,
  toonPopup,
  type Controle,
} from "../src/bijwerkstand.ts";

const controle: Controle = {
  huidige: "0.3.2",
  beschikbaar: true,
  versie: "0.4.0",
  notities: null,
  datum: null,
  soort: "prive",
};

test("elke vier uur, en 'je bent bij' staat vier seconden", () => {
  assert.equal(INTERVAL_MS, 4 * 60 * 60 * 1000);
  assert.equal(AFTEL_MS, 4000);
});

test("bij het starten en met de hand zie je elke fase", () => {
  for (const aanleiding of ["start", "hand"] as const) {
    assert.equal(toonPopup(aanleiding, { soort: "zoekt" }), true);
    assert.equal(toonPopup(aanleiding, { soort: "bij", huidige: "0.3.2" }), true);
    assert.equal(toonPopup(aanleiding, { soort: "nieuw", controle }), true);
    assert.equal(toonPopup(aanleiding, { soort: "fout", bericht: "x" }), true);
    assert.equal(toonPopup(aanleiding, { soort: "rust" }), false);
  }
});

test("de periodieke controle onderbreekt alleen als er echt iets is", () => {
  assert.equal(toonPopup("periodiek", { soort: "zoekt" }), false);
  assert.equal(toonPopup("periodiek", { soort: "bij", huidige: "0.3.2" }), false);
  assert.equal(toonPopup("periodiek", { soort: "fout", bericht: "x" }), false);
  assert.equal(toonPopup("periodiek", { soort: "nieuw", controle }), true);
  assert.equal(toonPopup("periodiek", { soort: "klaar", controle }), true);
});

test("alleen 'je bent bij' sluit zichzelf", () => {
  assert.equal(sluitVanzelf({ soort: "bij", huidige: "1" }), true);
  assert.equal(sluitVanzelf({ soort: "nieuw", controle }), false);
  assert.equal(sluitVanzelf({ soort: "fout", bericht: "x" }), false);
});

test("'laatst gecontroleerd' in gewone taal", () => {
  const nu = new Date(2026, 9, 15, 14, 30);
  assert.equal(laatstTekst(null, nu), "nog niet gecontroleerd");
  assert.equal(laatstTekst(new Date(2026, 9, 15, 14, 29, 40), nu), "zojuist gecontroleerd");
  assert.equal(laatstTekst(new Date(2026, 9, 15, 14, 5), nu), "25 min geleden gecontroleerd");
  assert.equal(laatstTekst(new Date(2026, 9, 15, 9, 2), nu), "vandaag om 09:02 gecontroleerd");
  assert.equal(laatstTekst(new Date(2026, 9, 14, 23, 50), nu), "gisteren om 23:50 gecontroleerd");
  assert.equal(laatstTekst(new Date(2026, 9, 12, 12, 0), nu), "3 dagen geleden gecontroleerd");
});

test("voortgang is een deel tussen 0 en 1, of onbekend", () => {
  assert.equal(deel(50, 200), 0.25);
  assert.equal(deel(300, 200), 1);
  assert.equal(deel(10, null), null);
  assert.equal(deel(10, 0), null);
});

test("fouten worden gewone zinnen", () => {
  assert.match(foutTekst(new Error("GitHub niet bereikbaar: dns error")), /Geen verbinding/);
  assert.match(foutTekst("geen release gevonden (of het token mag de repo niet lezen)"), /nog geen versie/);
  assert.match(foutTekst("deze build heeft geen updatetoken"), /installer/);
  assert.match(foutTekst("ophalen mislukt: signature mismatch"), /handtekening/);
  assert.equal(foutTekst("iets anders"), "iets anders");
});
