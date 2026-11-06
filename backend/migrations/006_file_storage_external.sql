-- A PDF is already compressed, so Postgres would not compress it anyway; EXTERNAL says so and lets
-- `substring(data from a for b)` read just those bytes of the stored value, which is how a Range
-- request is served. Applies to files stored from now on.
ALTER TABLE document_files ALTER COLUMN data SET STORAGE EXTERNAL;
