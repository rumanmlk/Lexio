export type HintInput = {
  streaming: boolean;
  error: unknown;
  refused: boolean | null;
  grounded: boolean | null;
  /** How many documents the search was narrowed to (0 = all of them). */
  scope: number;
};

/**
 * One line of advice under an answer that needs it, or null. A refusal means the documents
 * searched did not answer the question, which is often the question's fault (too vague, or
 * the wrong document selected); an answer with no citation is shown but cannot be trusted.
 */
export function answerHint(m: HintInput): string | null {
  if (m.streaming || m.error) return null;
  if (m.refused) {
    const narrowed =
      m.scope > 0
        ? `Only the ${m.scope === 1 ? "selected document was" : `${m.scope} selected documents were`} searched; untick to search them all. `
        : "";
    return `${narrowed}Try a more specific question, using terms from the document.`;
  }
  if (m.grounded === false) return "This answer doesn't cite a source, so check it against the documents.";
  return null;
}
