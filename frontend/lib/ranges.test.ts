import assert from "node:assert/strict";
import { test } from "node:test";
import { clampRange, parseContentRange, rangeHeader } from "./ranges.ts";
import { RefCache } from "./refcache.ts";

test("parseContentRange reads a partial response and rejects what it cannot trust", () => {
  assert.deepEqual(parseContentRange("bytes 0-99/1234"), { first: 0, last: 99, total: 1234 });
  assert.deepEqual(parseContentRange(" BYTES 10-19/20 "), { first: 10, last: 19, total: 20 });
  for (const bad of [null, "", "bytes 0-99/*", "bytes */1234", "bytes 5-2/10", "bytes 0-10/10", "items 0-1/2"]) {
    assert.equal(parseContentRange(bad), null, String(bad));
  }
});

test("rangeHeader and clampRange turn pdf.js's [begin, end) into HTTP's inclusive range", () => {
  assert.equal(rangeHeader(0, 99), "bytes=0-99");
  assert.deepEqual(clampRange(0, 100, 1000), [0, 99]);
  assert.deepEqual(clampRange(900, 1100, 1000), [900, 999]); // pdf.js may ask past the end
  assert.throws(() => clampRange(1000, 1100, 1000), RangeError);
  assert.throws(() => clampRange(-1, 10, 1000), RangeError);
});

function cache(max: number) {
  const made: string[] = [];
  const destroyed: string[] = [];
  const c = new RefCache<string>(
    (k) => (made.push(k), `v:${k}`),
    (v) => void destroyed.push(v),
    max,
  );
  return { c, made, destroyed };
}

test("RefCache shares one value per key and destroys the least recently used released one", () => {
  const { c, made, destroyed } = cache(2);
  for (const k of ["a", "b"]) c.acquire(k).release();
  const again = c.acquire("a"); // a is now newer than b
  again.release();
  assert.equal(again.value, "v:a");
  assert.deepEqual(made, ["a", "b"]);
  c.acquire("c").release(); // over the limit: b is the oldest
  assert.deepEqual(destroyed, ["v:b"]);
  assert.equal(c.size, 2);
});

test("RefCache never destroys a value that is in use, and keeps the size down once it is released", () => {
  const { c, destroyed } = cache(1);
  const a = c.acquire("a");
  const b = c.acquire("b");
  assert.deepEqual(destroyed, []); // both are held, so both stay even over the limit
  assert.equal(c.size, 2);
  b.release();
  assert.deepEqual(destroyed, ["v:b"]); // a is still held
  a.release();
  a.release(); // releasing twice does not take a second reference away
  assert.deepEqual(destroyed, ["v:b"]);
  assert.equal(c.size, 1); // a fits the limit, so it is kept for the next visit
  c.acquire("c").release();
  assert.deepEqual(destroyed, ["v:b", "v:a"]);
});

test("RefCache.forget drops a broken value so the next acquire makes a new one", () => {
  const { c, made, destroyed } = cache(3);
  const first = c.acquire("a");
  c.forget("a", first.value);
  assert.deepEqual(destroyed, ["v:a"]);
  first.release();
  c.acquire("a");
  assert.deepEqual(made, ["a", "a"]);
});
