import type { Source } from "./api.ts";

export type ChatEvent =
  | { type: "sources"; sources: Source[]; query: string }
  | { type: "token"; text: string }
  | { type: "done"; grounded: boolean; cited: number[]; refused: boolean }
  | { type: "error"; message: string; quota: boolean };

/** Turns one SSE block ("event: x\ndata: {...}") into a typed event, or null if unknown. */
export function parseBlock(block: string): ChatEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!name || data.length === 0) return null;
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(data.join("\n"));
  } catch {
    return null;
  }
  switch (name) {
    case "sources":
      return {
        type: "sources",
        sources: (body.sources as Source[]) ?? [],
        query: String(body.query ?? ""),
      };
    case "token":
      return { type: "token", text: String(body.text ?? "") };
    case "done":
      return {
        type: "done",
        grounded: Boolean(body.grounded),
        cited: (body.cited as number[]) ?? [],
        refused: Boolean(body.refused),
      };
    case "error":
      return { type: "error", message: String(body.message ?? "Something went wrong."), quota: Boolean(body.quota) };
    default:
      return null;
  }
}

/** Reads a byte stream and yields events as complete blocks arrive (blocks end in a blank line). */
export async function* readEvents(stream: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      // Normalize the whole buffer, not each chunk: a "\r\n" can be split between two chunks.
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
      }
      if (done) break;
    }
    const last = parseBlock(buffer.trim());
    if (last) yield last;
  } finally {
    reader.releaseLock();
  }
}
