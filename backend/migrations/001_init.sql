CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    text NOT NULL DEFAULT 'public',
    filename    text NOT NULL,
    sha256      text NOT NULL,
    page_count  integer NOT NULL,
    chunk_count integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, sha256)
);

-- 768 dims: gemini-embedding-2 truncated to 768 (Matryoshka) and bge-base-en for local dev.
CREATE TABLE chunks (
    id          bigserial PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    page        integer NOT NULL,
    content     text NOT NULL,
    embedding   vector(768) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX chunks_document_id ON chunks (document_id);
