-- Runs once, when the Docker volume is first initialised, to enable pgvector
-- in the photosphere database. The application also runs this idempotently on
-- first launch, so this is belt-and-braces.
CREATE EXTENSION IF NOT EXISTS vector;
