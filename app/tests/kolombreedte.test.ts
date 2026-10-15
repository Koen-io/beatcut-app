// node --test app/tests/kolombreedte.test.ts
//
// Verslepen is een manier om de app te slopen als er geen grenzen zijn, en de
// breedte blijft bewaard — dus een kolom die één keer te breed is gezet komt
// bij elke start terug. Dat is wat hier dichtgezet wordt.
import test from "node:test";
import assert from "node:assert/strict";

import {
  GROTE_STAP,
  MIN,
  STAP,
  breedteGrenzen,
  lees,
  nieuweBreedte,
} from "../src/kolombreedte.ts";

// ----------------------------------------------------------------- grenzen

test("een kolom mag de helft breder dan het ontwerp", () => {
  // Op een ruim venster is het ontwerp de grens: 2400 px, dus een derde is 800
  // en de factor van 1,5 wint.
  assert.deepEqual(breedteGrenzen(420, 2400), [294, 630]);
  assert.deepEqual(breedteGrenzen(232, 2400), [MIN, 348]);
});

test("een brede kolom mag minder ver krimpen dan een smalle", () => {
  // De stijlkaarten in stap 2 hebben een tegel van 124 px links. Op het vaste
  // minimum van 180 px bleef daar 24 px voor de tekst over.
  assert.equal(breedteGrenzen(380, 2400)[0], 266);
  assert.equal(breedteGrenzen(232, 2400)[0], MIN, "smal mag wel tot MIN");
});

test("op een smal venster is het venster de grens, niet het ontwerp", () => {
  // 1200 px breed: één kolom mag 400. Zonder dit kunnen twee kolommen van
  // 630 px het hele midden opeten — en staat die breedte ook nog bewaard.
  assert.deepEqual(breedteGrenzen(420, 1200), [294, 400]);
});

test("twee kolommen laten altijd een derde van het venster over", () => {
  // Stap 2 en 3 hebben er twee. Elke kolom hoogstens een derde, dus samen
  // hoogstens twee derde — zonder dat de een van de ander hoeft te weten.
  const [, max] = breedteGrenzen(420, 1400);
  // Een paar pixels marge voor het afronden naar hele pixels.
  assert.ok(1400 - 2 * max >= 1400 / 3 - 2, `midden ${1400 - 2 * max} px`);
});

test("op een heel smal venster klapt het klemmen niet om", () => {
  // 40 % van 300 px is 120, en dat is minder dan MIN. De bovengrens mag dan
  // nooit ónder de ondergrens zakken, want Math.min(max, Math.max(min, x))
  // levert dan de bovengrens en is de kolom plots 120 px.
  const [min, max] = breedteGrenzen(420, 300);
  assert.equal(min, 294);
  assert.equal(max, 294);
});

// ------------------------------------------------------------- toetsenbord

test("pijltjes verschuiven per stap, shift met grote stappen", () => {
  assert.equal(nieuweBreedte("ArrowRight", false, 300, 380, "links"), 300 + STAP);
  assert.equal(nieuweBreedte("ArrowLeft", false, 300, 380, "links"), 300 - STAP);
  assert.equal(nieuweBreedte("ArrowRight", true, 300, 380, "links"), 300 + GROTE_STAP);
});

test("een rechterkolom groeit naar links, dus daar is het omgekeerd", () => {
  // De greep hoort met de pijl mee te bewegen. Rechts betekent de pijl naar
  // links dus "greep naar links", en dat maakt die kolom breder.
  assert.equal(nieuweBreedte("ArrowLeft", false, 300, 420, "rechts"), 300 + STAP);
  assert.equal(nieuweBreedte("ArrowRight", false, 300, 420, "rechts"), 300 - STAP);
});

test("Home zet terug naar de breedte uit het ontwerp", () => {
  assert.equal(nieuweBreedte("Home", false, 600, 380, "links"), 380);
  // Enter en spatie doen hetzelfde: de greep is een knop, en wie hem met de
  // focus erop indrukt verwacht niet dat er niets gebeurt.
  assert.equal(nieuweBreedte("Enter", false, 600, 380, "links"), 380);
  assert.equal(nieuweBreedte(" ", false, 600, 380, "links"), 380);
});

test("andere toetsen doen niets, en blokkeren dus ook niets", () => {
  // Null betekent "niet van mij": Tab moet door kunnen naar het volgende
  // element, en preventDefault hoort er dan niet op te staan.
  assert.equal(nieuweBreedte("Tab", false, 300, 380, "links"), null);
  assert.equal(nieuweBreedte("ArrowUp", false, 300, 380, "links"), null);
});

// ---------------------------------------------------------------- opslag

/** Een localStorage die precies doet wat de test wil, inclusief stuk zijn. */
function nepOpslag(inhoud: Record<string, string>, stuk = false) {
  const echt = (globalThis as { localStorage?: Storage }).localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem(k: string) {
        if (stuk) throw new Error("opslag staat uit");
        return inhoud[k] ?? null;
      },
      setItem(k: string, v: string) {
        if (stuk) throw new Error("opslag staat uit");
        inhoud[k] = v;
      },
    },
  });
  return () => Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: echt,
  });
}

test("zonder bewaarde breedte geldt het ontwerp", () => {
  const terug = nepOpslag({});
  try {
    assert.equal(lees("media", 232, 1600), 232);
  } finally {
    terug();
  }
});

test("een bewaarde breedte komt terug", () => {
  const terug = nepOpslag({ "beatcut.kolom.media": "300" });
  try {
    assert.equal(lees("media", 232, 1600), 300);
  } finally {
    terug();
  }
});

test("een breedte van een groter venster wordt teruggeklemd", () => {
  // Bewaard op een 2560 px scherm, nu op een laptop van 1280: 630 px zou daar
  // de halve breedte zijn. Dit is het geval waarin de app anders al bij het
  // openen onbruikbaar is.
  const terug = nepOpslag({ "beatcut.kolom.exporteren": "630" });
  try {
    assert.equal(lees("exporteren", 420, 1280), 427);
  } finally {
    terug();
  }
});

test("rommel in de opslag levert het ontwerp op, geen NaN-kolom", () => {
  const terug = nepOpslag({ "beatcut.kolom.media": "heel breed graag" });
  try {
    assert.equal(lees("media", 232, 1600), 232);
  } finally {
    terug();
  }
});

test("opslag die helemaal niet mag levert het ontwerp op", () => {
  // Privémodus of geblokkeerde site-data. Een uitzondering hier zou het hele
  // scherm wit maken bij het eerste renderen.
  const terug = nepOpslag({}, true);
  try {
    assert.equal(lees("media", 232, 1600), 232);
  } finally {
    terug();
  }
});
