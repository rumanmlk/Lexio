-- The original PDF, so the UI can show the page an answer cites. Kept apart from `documents`
-- so listing documents never reads file bytes.
CREATE TABLE document_files (
    document_id uuid  PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    data        bytea NOT NULL
);
