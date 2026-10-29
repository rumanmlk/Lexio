-- Phase 3: documents belong to a signed-in user ("google:<sub>") or to the shared sample set.
-- The sample set was called 'public'; renaming it moves no data. UNIQUE (owner_id, sha256)
-- already indexes owner_id, so no separate index is needed for the per-owner lookups.
UPDATE documents SET owner_id = 'samples' WHERE owner_id = 'public';
-- Nothing should land in a shared owner by omission any more.
ALTER TABLE documents ALTER COLUMN owner_id DROP DEFAULT;

-- File size kept on the row so per-user storage caps never read the PDF bytes.
ALTER TABLE documents ADD COLUMN size_bytes bigint NOT NULL DEFAULT 0;
UPDATE documents d SET size_bytes = octet_length(f.data)
FROM document_files f WHERE f.document_id = d.id;
