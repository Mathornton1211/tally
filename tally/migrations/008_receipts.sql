-- Receipts, and the transaction each one belongs to.
--
-- The file itself lives on disk (RECEIPTS_DIR), not in Postgres: a database of
-- photos is a database that cannot be dumped in a second. The row carries what
-- was read off the receipt and where the file went.

CREATE TABLE receipts (
    id            bigserial PRIMARY KEY,
    filename      text NOT NULL,          -- what the user's phone called it
    stored_name   text NOT NULL UNIQUE,   -- what it is called on disk
    content_type  text NOT NULL,
    bytes         integer NOT NULL,
    sha256        text NOT NULL UNIQUE,   -- same photo twice is the same receipt
    -- Read off the image when OCR is available; editable either way.
    amount        numeric(14,2),
    receipt_date  date,
    merchant      text,
    ocr_text      text,
    ocr_source    text,                   -- tesseract | manual | none
    transaction_id text REFERENCES transactions(id) ON DELETE SET NULL,
    matched_by    text,                   -- auto | user
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX receipts_txn_idx ON receipts (transaction_id);
CREATE INDEX receipts_unmatched_idx ON receipts (created_at DESC) WHERE transaction_id IS NULL;
