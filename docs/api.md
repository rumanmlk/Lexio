# API

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/documents` | signed-in only: multipart PDF upload (used when `BLOB_READ_WRITE_TOKEN` is not set, e.g. locally); deduplicated by SHA-256, and a PDF identical to a sample returns the sample |
| `POST` | `/api/upload-ticket` | signed-in only, only with Blob: the checks that do not need the file (caps, uploads switch, tickets per day); returns the user's storage prefix. Called by the web app's `/blob-upload` route before it lets the browser upload |
| `POST` | `/api/documents/register` | signed-in only, only with Blob: `{pathname, filename}` of a PDF the browser already uploaded; the API checks it is under the caller's prefix, reads, indexes and keeps it, or deletes it if rejected or a duplicate |
| `GET` | `/api/documents` | the samples plus the caller's own (`sample: true` marks the shared ones) |
| `GET` | `/api/documents/{id}/file` | the original PDF, for the viewer |
| `DELETE` | `/api/documents/{id}` | signed-in only: delete one of your documents with its chunks (`403` for a sample) |
| `DELETE` | `/api/me` | signed-in only: erase all of your documents and files |
| `GET` | `/api/limits` | what this visitor may still do today (questions, uploads, stored documents, reset time) |
| `POST` | `/api/chat` | `{question, document_ids?, history?}`, answers as Server-Sent Events: `sources` (with the `query` actually searched), `token`…, `done` (`grounded`, `cited`, `refused`) or `error` |

Errors are explicit: a used-up daily budget returns `429` with `Retry-After` (see [operations](operations.md#running-a-public-demo-inside-those-limits)); unreadable, password-protected or scanned (no text layer) PDFs return `422` with a reason; a rejected API key returns `502` and a rate limit or timeout returns `503`, after retries with backoff. If the LLM fails after streaming has started, the stream ends with an `error` event.
