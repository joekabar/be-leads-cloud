-- Suppression list: people and companies that must not appear in any export.
--
-- GDPR Art. 21 makes the right to object absolute for direct marketing, and Art. 17
-- grants erasure. Neither can be honoured by deleting from `observations`, which is
-- append-only by design: canonical facts are never overwritten, and the provenance trail
-- is the thing that makes this dataset defensible in the first place.
--
-- So suppression is a separate, mutable layer. The observation stays as the record of
-- what was seen and when; the export refuses to emit it. That satisfies the request
-- without falsifying history.
--
-- An entry may key on any identifier the objector actually gave us — most people say
-- "stop calling this number" or "remove this address", not "erase KBO 0123456789" — so
-- all three are nullable and at least one must be present.

CREATE TABLE IF NOT EXISTS suppression_list (
    id           BIGSERIAL   PRIMARY KEY,
    kbo_number   CHAR(10),
    email        TEXT,
    phone        TEXT,
    -- Why the entry exists. Free text so a request can be described in the words used.
    reason       TEXT        NOT NULL,
    -- Who recorded it, for audit.
    recorded_by  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT suppression_needs_an_identifier
        CHECK (kbo_number IS NOT NULL OR email IS NOT NULL OR phone IS NOT NULL)
);

-- Lookups are one query per export over a small table, but the export runs on every
-- schedule tick and the table only grows.
CREATE INDEX IF NOT EXISTS idx_suppression_kbo   ON suppression_list (kbo_number)
    WHERE kbo_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_suppression_email ON suppression_list (lower(email))
    WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_suppression_phone ON suppression_list (phone)
    WHERE phone IS NOT NULL;
