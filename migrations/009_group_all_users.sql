-- Allow group-wide monitored sources by permitting NULL user_id for groups

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'monitored_sources'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%chat_type = ''group'' AND user_id IS NOT NULL%'
    LOOP
        EXECUTE format('ALTER TABLE monitored_sources DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;

ALTER TABLE monitored_sources
    DROP CONSTRAINT IF EXISTS monitored_sources_chat_user_check;

ALTER TABLE monitored_sources
    ADD CONSTRAINT monitored_sources_chat_user_check
    CHECK (
        (chat_type = 'group')
        OR (chat_type IN ('channel', 'dm') AND user_id IS NULL)
    );
