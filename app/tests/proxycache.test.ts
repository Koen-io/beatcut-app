// node --test app/tests/proxycache.test.ts
//
// De speler hield elke proxy vast die ooit geladen was (nalooprond 05-10).
// Dit legt het plafond vast, en dat een proxy met een decoder eraan blijft.
import test from "node:test";
import assert from "node:assert/strict";

import { ProxyCache } from "../src/speler/proxycache.ts";

const tik = () => new Promise<void>((r) => setTimeout(r, 0));
const proxy = (bytes: number) => Promise.resolve({ bytes });

test("dezelfde proxy wordt één keer gelezen", async () => {
  const c = new ProxyCache<{ bytes: number }>(1000, 10);
  let gelezen = 0;
  const lees = () => {
    gelezen++;
    return proxy(10);
  };
  const a = c.haal("a", lees);
  const b = c.haal("a", lees);
  assert.equal(a, b);
  assert.equal(gelezen, 1);
  await tik();
  assert.equal(c.totaalBytes(), 10);
});

test("boven het aantal gaat de minst recent gebruikte eruit", async () => {
  const c = new ProxyCache<{ bytes: number }>(1_000_000, 2);
  void c.haal("a", () => proxy(1));
  void c.haal("b", () => proxy(1));
  void c.haal("a", () => proxy(1)); // a is nu recenter dan b
  void c.haal("c", () => proxy(1));
  await tik();
  assert.equal(c.heeft("b"), false);
  assert.equal(c.heeft("a"), true);
  assert.equal(c.heeft("c"), true);
});

test("boven de bytes gaat de oudste eruit zodra de grootte bekend is", async () => {
  const c = new ProxyCache<{ bytes: number }>(100, 10);
  void c.haal("a", () => proxy(60));
  await tik();
  void c.haal("b", () => proxy(60));
  await tik();
  assert.equal(c.heeft("a"), false);
  assert.equal(c.heeft("b"), true);
  assert.equal(c.totaalBytes(), 60);
});

test("wat vast staat blijft, ook boven het plafond", async () => {
  const c = new ProxyCache<{ bytes: number }>(100, 1);
  const vast = new Set(["a"]);
  void c.haal("a", () => proxy(60), vast);
  await tik();
  void c.haal("b", () => proxy(60), vast);
  await tik();
  assert.equal(c.heeft("a"), true, "a hangt aan een decoder");
  assert.equal(c.heeft("b"), true, "b is net gevraagd en staat zelf vast");
  // Zodra a niet meer vast is, gaat hij bij de volgende opruiming weg.
  assert.deepEqual(c.ruimOp(new Set(["b"])), ["a"]);
});

test("een mislukte lezing blijft niet hangen", async () => {
  const c = new ProxyCache<{ bytes: number }>(100, 10);
  await c.haal("a", () => Promise.reject(new Error("kapot"))).catch(() => {});
  await tik();
  assert.equal(c.heeft("a"), false);
  assert.equal(c.aantal, 0);
});
