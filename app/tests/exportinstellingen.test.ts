// node --test app/tests/exportinstellingen.test.ts
import test from "node:test";
import assert from "node:assert/strict";

import {
  STANDAARD, actieveVoorinstelling, bewaar, bitrateTekst, isStandaard, laad,
  metVoorinstelling, pasAan, schoneNaam,
} from "../src/exportinstellingen.ts";
import type { Exportmogelijkheden } from "../src/engine.ts";

/** Een computer die alles kan, tenzij `zonder` iets wegneemt. */
function kan(zonder: string[] = []): Exportmogelijkheden {
  const v = (lijst: string[]) => lijst.filter((c) => !zonder.includes(c));
  return {
    containers: [
      { id: "mp4", label: "MP4", video: v(["h264", "hevc"]), audio: ["aac", "geen"] },
      { id: "mov", label: "MOV", video: v(["h264", "hevc", "prores"]), audio: ["aac", "alac", "pcm", "geen"] },
      { id: "mkv", label: "MKV", video: v(["h264", "hevc", "prores"]), audio: ["aac", "flac", "pcm", "geen"] },
    ],
    codecs: [],
    audio: [],
    kwaliteit: ["klein", "standaard", "hoog", "eigen"].map((id) => ({ id, label: id })),
    prores: ["proxy", "lt", "standaard", "hq"].map((id) => ({ id, label: id })),
    resoluties: ["bron", "2160", "1440", "720", "540"].map((id) => ({
      id, label: id, breedte: 0, hoogte: 0, opgeschaald: false,
    })),
    fps: [24, 25, 30, 50, 60],
    audio_kbps: [128, 192, 256, 320],
    samplerates: [48000, 44100],
    bitrate: { min: 1, max: 200 },
    bron: { breedte: 1920, hoogte: 1080, fps: 30, duur: 60 },
    standaardmap: "/p/renders/export",
    voorinstellingen: [
      { id: "standaard", label: "Standaard", keuze: {} },
      { id: "delen", label: "Klein", keuze: { codec: "hevc", resolutie: "720", kwaliteit: "klein", audio_kbps: 128 } },
      { id: "bewerken", label: "Bewerken", keuze: { container: "mov", codec: "prores", audio: "pcm" } },
    ].filter((x) => !zonder.includes(x.keuze.codec ?? "h264")),
  };
}

function opslag(begin: Record<string, string> = {}) {
  const d = { ...begin };
  return {
    getItem: (k: string) => d[k] ?? null,
    setItem: (k: string, v: string) => { d[k] = v; },
    d,
  };
}

test("de standaard is precies wat de render maakt", () => {
  assert.equal(isStandaard(STANDAARD), true);
  assert.equal(isStandaard({ ...STANDAARD, audio_kbps: 256 }), false);
  // Map en naam veranderen het bestand niet, alleen waar het komt.
  assert.equal(isStandaard({ ...STANDAARD, map: "/x", naam: "y" }), true);
});

test("van MOV met ProRes naar MP4: alleen wat niet past verandert", () => {
  const mov = { ...STANDAARD, container: "mp4", codec: "prores", audio: "pcm", resolutie: "720", map: "/uit" };
  const uit = pasAan(mov, kan());
  assert.equal(uit.codec, "h264");
  assert.equal(uit.audio, "aac");
  assert.equal(uit.resolutie, "720");
  assert.equal(uit.map, "/uit");
});

test("een codec die deze computer niet kan maken wordt nooit gekozen", () => {
  const uit = pasAan({ ...STANDAARD, codec: "hevc" }, kan(["hevc"]));
  assert.equal(uit.codec, "h264");
});

test("een bewaarde keuze met onzin erin valt per veld terug op de standaard", () => {
  const o = opslag({ "beatcut.export": JSON.stringify({
    container: "mov", codec: 7, bitrate: "veel", audio_kbps: 256, naam: "oud", map: "/uit",
  }) });
  const k = laad(o);
  assert.equal(k.container, "mov");
  assert.equal(k.codec, "h264");
  assert.equal(k.bitrate, 12);
  assert.equal(k.audio_kbps, 256);
  assert.equal(k.map, "/uit");
  assert.equal(k.naam, "", "de naam hoort bij één video en wordt niet onthouden");
});

test("kapotte opslag is geen fout", () => {
  assert.deepEqual(laad(opslag({ "beatcut.export": "{niet json" })), STANDAARD);
  assert.deepEqual(laad(opslag()), STANDAARD);
});

test("bewaren en laden geeft dezelfde keuze terug, zonder de naam", () => {
  const o = opslag();
  bewaar(o, { ...STANDAARD, codec: "hevc", naam: "vakantie", map: "/uit" });
  assert.deepEqual(laad(o), { ...STANDAARD, codec: "hevc", map: "/uit" });
});

test("een bitrate buiten het bereik wordt geklemd", () => {
  assert.equal(pasAan({ ...STANDAARD, bitrate: 900 }, kan()).bitrate, 200);
  assert.equal(pasAan({ ...STANDAARD, bitrate: 0 }, kan()).bitrate, 1);
});

test("een voorinstelling laat map en naam staan", () => {
  const m = kan();
  const uit = metVoorinstelling({ ...STANDAARD, map: "/uit", naam: "film" }, m.voorinstellingen[2].keuze, m);
  assert.equal(uit.container, "mov");
  assert.equal(uit.codec, "prores");
  assert.equal(uit.map, "/uit");
  assert.equal(uit.naam, "film");
});

test("het menu weet welke voorinstelling er staat, en wanneer het iets eigens is", () => {
  const m = kan();
  assert.equal(actieveVoorinstelling({ ...STANDAARD, map: "/uit" }, m), "standaard");
  assert.equal(actieveVoorinstelling(metVoorinstelling(STANDAARD, m.voorinstellingen[1].keuze, m), m), "delen");
  assert.equal(actieveVoorinstelling({ ...STANDAARD, fps: "25" }, m), null);
  // Een bitrate die niet meedoet mag de voorinstelling niet "eigen" maken.
  assert.equal(actieveVoorinstelling({ ...STANDAARD, bitrate: 40 }, m), "standaard");
});

test("bitrates lezen als Mbit/s of kbit/s, met een komma", () => {
  assert.equal(bitrateTekst(9_331_200), "9,3 Mbit/s");
  assert.equal(bitrateTekst(220_000_000), "220 Mbit/s");
  assert.equal(bitrateTekst(192_000), "192 kbit/s");
});

test("verboden tekens gaan uit de bestandsnaam", () => {
  assert.equal(schoneNaam('va/ka:n"tie?'), "vakantie");
});

test("dezelfde beeldsnelheid als de montage is gewoon 'zoals de montage'", () => {
  // Anders ziet de engine een omzetting waar niets verandert, en mist de
  // keuzelijst de optie die geselecteerd zou moeten staan.
  assert.equal(pasAan({ ...STANDAARD, fps: "30" }, kan()).fps, "bron");
  assert.equal(pasAan({ ...STANDAARD, fps: "25" }, kan()).fps, "25");
});
