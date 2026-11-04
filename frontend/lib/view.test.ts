import assert from "node:assert/strict";
import { test } from "node:test";

import { boxesFor, buildIndex, findPassage, squash } from "./highlight.ts";
import { docSource, docTitle } from "./title.ts";

test("docTitle names the samples and tidies other filenames", () => {
  assert.equal(docTitle("Mutual-NDA-public-2page.pdf"), "Mutual NDA");
  assert.equal(docTitle("CELEX_32016R0679_EN_TXT.pdf"), "GDPR (Regulation 2016/679)");
  assert.equal(docTitle("my_lease_2024.pdf"), "my lease 2024");
  assert.equal(docTitle("My-Test-Lease_2024.pdf"), "My Test Lease 2024");
  assert.equal(docTitle(".pdf"), ".pdf");
  assert.equal(docSource("crc.pdf"), "United Nations");
  assert.equal(docSource("my_lease_2024.pdf"), null);
});

test("squash keeps letters and digits only", () => {
  assert.equal(squash("The Receiving Party’s “MNDA” (v1.0)"), "thereceivingpartysmndav10");
});

const items = [
  { str: "2. Use and Protection of Confidential Information. The Receiving Party shall: (a) use Confidential " },
  { str: "Information solely for the Purpose; (b) not disclose Confidential Information to third parties without the " },
  { str: "Disclosing Party’s prior written approval, except that the Receiving Party may disclose it to its employees." },
];

test("findPassage places a passage that starts mid-page and spans items", () => {
  // pypdf text: different spacing, a replacement character where the apostrophe is.
  const passage = "Information solely for the Purpose;  (b) not disclose Confidential Information to third parties without the Disclosing Party�s prior written approval";
  const span = findPassage(buildIndex(items), passage);
  assert.ok(span);
  assert.equal(span.first, 1);
  assert.equal(span.firstOffset, 0);
  assert.equal(span.last, 2);
  assert.ok(span.lastOffset > 20 && span.lastOffset <= items[2].str.length);
});

test("findPassage gives up when the text is not on the page", () => {
  assert.equal(findPassage(buildIndex(items), "Nothing like this appears anywhere in the extracted text of the page"), null);
  assert.equal(findPassage(buildIndex(items), "too short"), null);
});

test("boxesFor trims the first and last items to the characters used", () => {
  const placed = [
    { str: "abcd", left: 10, top: 5, width: 40, height: 10 },
    { str: "efgh", left: 10, top: 20, width: 40, height: 10 },
  ];
  const boxes = boxesFor(placed, { first: 0, firstOffset: 2, last: 1, lastOffset: 2 });
  assert.deepEqual(boxes, [
    { left: 30, top: 5, width: 20, height: 10 },
    { left: 10, top: 20, width: 20, height: 10 },
  ]);
});
