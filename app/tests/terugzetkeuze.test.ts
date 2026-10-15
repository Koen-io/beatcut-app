// node --test app/tests/terugzetkeuze.test.ts  (Node 24 leest TypeScript zelf)
import test from "node:test";
import assert from "node:assert/strict";

import {
  bestandsnaam,
  bronnenTekst,
  datumTekst,
  naamUitleg,
  ontbrekend,
  teruggezetTekst,
  wachtTekst,
  type Kopie,
  type KopieBron,
} from "../src/terugzetkeuze.ts";

const bron = (naam: string, pad: string | null, oud: string | null = `/camera/${naam}`): KopieBron => ({
  naam,
  bytes: 83_000_000,
  oud,
  pad,
});

function kopie(bronnen: KopieBron[], anders: Partial<Kopie> = {}): Kopie {
  return {
    pad: "/Users/koen/Desktop/vakantie (BeatCut-kopie 2026-10-04).zip",
    project: "vakantie",
    naam: "vakantie",
    bezet: false,
    gemaakt: "2026-10-04T12:10:00+00:00",
    beatcut: "2.0.0",
    aantal_clips: bronnen.length,
    bronnen,
    proxies: true,
    heeft_montage: true,
    heeft_muziek: true,
    bytes: 6_400_000,
    uitgepakt: 6_500_000,
    ...anders,
  };
}

test("de datum staat in de tijd van de computer, niet in UTC", () => {
  assert.equal(datumTekst("2026-10-04T12:10:00+00:00", "Europe/Amsterdam"), "4 oktober 2026 om 14:10");
  assert.equal(datumTekst("2026-10-04T23:30:00+00:00", "Europe/Amsterdam"), "5 oktober 2026 om 01:30");
});

test("een kopie zonder bruikbare datum zegt dat eerlijk", () => {
  assert.equal(datumTekst(null), "onbekend");
  assert.equal(datumTekst("gisteren"), "onbekend");
});

test("de bestandsnaam komt uit een Mac-pad én uit een Windows-pad", () => {
  assert.equal(bestandsnaam("/Users/koen/Desktop/kopie.zip"), "kopie.zip");
  assert.equal(bestandsnaam("C:\\Users\\koen\\Desktop\\kopie.zip"), "kopie.zip");
  assert.equal(bestandsnaam("kopie.zip"), "kopie.zip");
});

test("alles gevonden: geruststelling, en het origineel blijft staan", () => {
  const t = bronnenTekst(kopie([bron("a.mp4", "/camera/a.mp4"), bron("b.mp4", "/camera/b.mp4")]));
  assert.equal(t.toon, "ok");
  assert.equal(t.kop, "Alle 2 video's zijn gevonden.");
  assert.match(t.uitleg, /originelen blijven waar ze zijn/);
  assert.equal(bronnenTekst(kopie([bron("a.mp4", "/camera/a.mp4")])).kop, "De video is gevonden.");
});

test("een deel ontbreekt: het aantal klopt en de zin loopt in enkelvoud en meervoud", () => {
  const k = kopie([bron("a.mp4", null), bron("b.mp4", "/camera/b.mp4"), bron("c.mp4", null)]);
  assert.deepEqual(ontbrekend(k).map((b) => b.naam), ["a.mp4", "c.mp4"]);
  assert.equal(bronnenTekst(k).toon, "let-op");
  assert.equal(bronnenTekst(k).kop, "2 van de 3 video's staan niet meer waar ze stonden.");
  const een = kopie([bron("a.mp4", null), bron("b.mp4", "/camera/b.mp4")]);
  assert.equal(bronnenTekst(een).kop, "1 van de 2 video's staat niet meer waar hij stond.");
  assert.equal(bronnenTekst(kopie([bron("a.mp4", null)])).kop, "De video staat niet meer waar hij stond.");
  assert.equal(
    bronnenTekst(kopie([bron("a.mp4", null), bron("b.mp4", null)])).kop,
    "Geen van de 2 video's staat nog waar hij stond.",
  );
});

test("zonder voorvertoningen staat erbij dat de montage even niet te bekijken is", () => {
  const mis = [bron("a.mp4", null)];
  assert.doesNotMatch(bronnenTekst(kopie(mis)).uitleg, /niet te bekijken/);
  assert.match(bronnenTekst(kopie(mis, { proxies: false })).uitleg, /niet te bekijken/);
  assert.match(bronnenTekst(kopie(mis)).uitleg, /zet het project toch terug/);
});

test("een oudere kopie weet niet waar de video's stonden, en zegt dat zo", () => {
  const k = kopie([bron("a.mp4", null, null), bron("b.mp4", null, null)]);
  assert.equal(bronnenTekst(k).kop, "BeatCut weet niet waar de 2 video's van dit project staan.");
});

test("na het aanwijzen van een map gaat de zin over die map", () => {
  const k = kopie([bron("a.mp4", null), bron("b.mp4", "/archief/b.mp4"), bron("c.mp4", "/archief/c.mp4")]);
  assert.equal(bronnenTekst(k, true).kop, "Daar is er nog 1 van de 3 niet gevonden.");
});

test("een project zonder video's krijgt geen waarschuwing", () => {
  assert.equal(bronnenTekst(kopie([])).toon, "geen");
});

test("bestaat de naam al, dan staat erbij welke naam het wordt en dat er niets overschreven wordt", () => {
  const k = kopie([], { naam: "vakantie-2", bezet: true });
  assert.equal(
    naamUitleg(k, null),
    'Er staat al een project "vakantie". De kopie komt ernaast, als "vakantie-2". Er wordt niets overschreven.',
  );
  assert.equal(
    naamUitleg(k, "vakantie"),
    'Die naam is al in gebruik. Het wordt "vakantie-2". Er wordt niets overschreven.',
  );
});

test("een vrije naam geeft geen uitleg, een opgeschoonde wel", () => {
  assert.equal(naamUitleg(kopie([]), null), null);
  assert.equal(naamUitleg(kopie([], { naam: "zomer" }), " zomer "), null);
  assert.equal(naamUitleg(kopie([], { naam: "zomer-2026" }), "Zomer 2026!"), 'Het project gaat "zomer-2026" heten.');
});

test("de melding na afloop zegt wat er weer bij is en wat nog ontbreekt", () => {
  const uit = { naam: "vakantie", gekoppeld: ["a.mp4", "b.mp4"], ontbreekt: [], verwerken: false };
  assert.equal(teruggezetTekst(uit), "2 video's zijn er weer bij.");
  assert.equal(teruggezetTekst({ ...uit, gekoppeld: ["a.mp4"] }), "De video is er weer bij.");
  assert.equal(
    teruggezetTekst({ ...uit, verwerken: true }),
    "2 video's zijn er weer bij. De voorvertoningen worden opnieuw gemaakt.",
  );
  assert.equal(
    teruggezetTekst({ ...uit, gekoppeld: ["a.mp4"], ontbreekt: ["b.mp4"] }),
    "1 video is er weer bij. 1 video ontbreekt nog: sleep hem in het project.",
  );
  assert.equal(
    teruggezetTekst({ ...uit, gekoppeld: [], ontbreekt: ["a.mp4", "b.mp4"] }),
    "2 video's ontbreken nog: sleep ze in het project.",
  );
  assert.equal(teruggezetTekst({ ...uit, gekoppeld: [] }), "");
});

test("de wachtbalk noemt de video's bij naam, en loopt in enkelvoud en meervoud", () => {
  const een = wachtTekst(["strand-2.mp4"]);
  assert.equal(een.kop, "Dit project wacht nog op 1 video");
  assert.match(een.uitleg, /^strand-2\.mp4\. Sleep hem hierheen: BeatCut zet hem terug op zijn plek/);
  const twee = wachtTekst(["a.mp4", "b.mp4"]);
  assert.equal(twee.kop, "Dit project wacht nog op 2 video's");
  assert.match(twee.uitleg, /^a\.mp4, b\.mp4\. Sleep ze hierheen: BeatCut zet ze terug op hun plek/);
  assert.match(twee.uitleg, /niets opnieuw ingelezen/);
});

test("bij veel ontbrekende video's staan er vier bij naam en de rest als aantal", () => {
  const veel = wachtTekst(["a.mp4", "b.mp4", "c.mp4", "d.mp4", "e.mp4", "f.mp4"]);
  assert.match(veel.uitleg, /^a\.mp4, b\.mp4, c\.mp4, d\.mp4 en nog 2\. /);
});
