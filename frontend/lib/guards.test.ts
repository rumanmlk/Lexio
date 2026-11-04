import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { LOGO } from "./logo.ts";
import { SAMPLE_QUESTIONS } from "./samples.ts";
import { docSource } from "./title.ts";

const root = new URL("../../", import.meta.url);

test("every sample PDF has a curated title", () => {
  const pdfs = fs.readdirSync(new URL("data/samples/", root)).filter((f) => f.toLowerCase().endsWith(".pdf"));
  assert.ok(pdfs.length >= 9);
  const missing = pdfs.filter((f) => docSource(f) === null);
  assert.deepEqual(missing, [], "add these to KNOWN in lib/title.ts");
});

test("the suggested questions are questions the evaluation set verifies", () => {
  const dataset: { question: string; answerable: boolean }[] = JSON.parse(
    fs.readFileSync(new URL("backend/evals/dataset.json", root), "utf8"),
  );
  const verified = new Set(dataset.filter((q) => q.answerable).map((q) => q.question));
  assert.deepEqual(SAMPLE_QUESTIONS.filter((q) => !verified.has(q)), []);
});

test("app/icon.svg draws the same shapes as the logo", () => {
  const svg = fs.readFileSync(new URL("frontend/app/icon.svg", root), "utf8");
  const drawn = [...svg.matchAll(/<rect\b([^>]*)\/>/g)].map((m) => {
    const attr = (name: string) => Number(new RegExp(String.raw`(?:^|\s)${name}="([\d.]+)"`).exec(m[1])?.[1] ?? 0);
    return { x: attr("x"), y: attr("y"), width: attr("width"), height: attr("height"), rx: attr("rx") };
  });
  assert.deepEqual(drawn, LOGO.map(({ role: _role, ...r }) => r));
});
