// node --test app/tests/onderdelenstand.test.ts  (Node 24 leest TypeScript zelf)
import test from "node:test";
import assert from "node:assert/strict";

import { standNaFout } from "../src/onderdelenstand.ts";

test("zelf gestopt is geen storing: de stand wordt 'mist'", () => {
  const stand = standNaFout({
    fout: "Het klaarzetten is gestopt. Wat er al stond blijft staan.",
    soort: "Gestopt",
  });

  assert.deepEqual(stand, { soort: "mist" });
});

test("een echte fout blijft een fout, met de tekst van de engine", () => {
  const stand = standNaFout({ fout: "Geen verbinding met npm.", soort: "OSError" });

  assert.deepEqual(stand, { soort: "fout", bericht: "Geen verbinding met npm." });
});
