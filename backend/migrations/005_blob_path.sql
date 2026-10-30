-- Phase 4: PDFs uploaded straight to object storage (Vercel Blob) are kept there, not in
-- document_files. `blob_path` is the object's pathname; NULL for documents whose PDF is in Postgres.
ALTER TABLE documents ADD COLUMN blob_path text;
