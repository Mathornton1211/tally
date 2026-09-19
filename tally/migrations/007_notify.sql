-- Push notifications and the weekly brief.

-- Nothing is ever sent twice: an alert carries the moment it went out.
ALTER TABLE alerts ADD COLUMN notified_at timestamptz;

CREATE TABLE notifications (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,          -- alert | brief | test
    title       text NOT NULL,
    body        text NOT NULL,
    priority    integer NOT NULL DEFAULT 3,
    alert_id    bigint REFERENCES alerts(id) ON DELETE SET NULL,
    ok          boolean NOT NULL,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_created_idx ON notifications (created_at DESC);
