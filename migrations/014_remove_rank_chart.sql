ALTER TABLE rank_forwarding_rules
    DROP COLUMN IF EXISTS post_chart_request,
    DROP COLUMN IF EXISTS chart_request_chat_id,
    DROP COLUMN IF EXISTS chart_request_text;
