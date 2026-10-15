// node --test app/tests/blobbron.test.ts
//
// De crash van 15-10-2026: afgebroken mediaverzoeken over het tauri://-
// protocol. Tegels en muziek gaan sindsdien één keer helemaal binnen als
// `blob:`. Dit legt vast dat dat één keer per adres gebeurt, en dat een
// mislukte poging niet onthouden wordt.
import test from "node:test";
import assert from "node:assert/strict";

import { blobAantal, blobBron } from "../src/blobbron.ts";

test("één ophaalbeurt per adres, ook bij gelijktijdige vragen", async () => {
  let gehaald = 0;
  globalThis.fetch = (async () => {
    gehaald++;
    return new Response(new Blob(["film"]), { status: 200 });
  }) as typeof fetch;
  const [a, b] = await Promise.all([blobBron("/x.mp4"), blobBron("/x.mp4")]);
  assert.equal(a, b);
  assert.ok(a.startsWith("blob:"));
  assert.equal(gehaald, 1);
  await blobBron("/x.mp4");
  assert.equal(gehaald, 1);
});

test("een mislukte ophaalbeurt wordt opnieuw geprobeerd", async () => {
  let keer = 0;
  globalThis.fetch = (async () => {
    keer++;
    return keer === 1 ? new Response(null, { status: 404 }) : new Response(new Blob(["x"]));
  }) as typeof fetch;
  const voor = blobAantal();
  await assert.rejects(blobBron("/weg.mp4"));
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(blobAantal(), voor);
  assert.ok((await blobBron("/weg.mp4")).startsWith("blob:"));
  assert.equal(keer, 2);
});
