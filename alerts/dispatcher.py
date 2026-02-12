"""
Gain alert dispatcher - formats and routes gain alerts to destination chats.
"""

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE, missing_required_placeholders
from alerts.thresholds import compute_threshold
from charts.guardrail_evaluator import (
    evaluate_chart_guardrails,
    format_guardrail_summary,
)
from config import DEFAULT_GLOBAL_CHART_THRESHOLD
from db import db
from models import MonitoredSourceModel, SettingsModel
from utils.structured_logging import log_event

logger = logging.getLogger(__name__)


class GainAlertDispatcher:
    def __init__(
        self,
        settings_model: SettingsModel,
        source_model: MonitoredSourceModel,
        dex_client,
    ) -> None:
        self.settings_model = settings_model
        self.source_model = source_model
        self.dex_client = dex_client

    async def dispatch_gain_alert(
        self,
        token: Dict[str, Any],
        template_values: Dict[str, str],
        address: str,
        current_mc: Decimal,
        *,
        userbot_manager,
        management_bot,
        chart_fetcher,
        format_mc_shorthand,
    ) -> bool:
        try:
            token_id = token["id"]

            tracking_groups = await db.fetch(
                """
                SELECT
                    tga.chat_id,
                    tga.original_message_id,
                    tga.first_seen_mc,
                    tga.last_alert_mc,
                    tga.original_user_id,
                    ms.id AS source_id,
                    ms.user_id AS source_user_id,
                    ms.is_enabled,
                    ms.sensitivity_pct,
                    ms.assigned_userbot_id,
                    ms.template_text,
                    ms.use_management_bot,
                    ms.chart_enabled,
                    ms.chart_bot_id,
                    ms.chart_mc_threshold,
                    ARRAY_REMOVE(ARRAY_AGG(mst.target_chat_id), NULL) AS extra_targets
                FROM token_group_alerts tga
                LEFT JOIN LATERAL (
                    SELECT ms.*
                    FROM monitored_sources ms
                    WHERE ms.chat_id = tga.chat_id
                      AND (
                            ms.user_id = tga.original_user_id
                            OR (ms.chat_type = 'group' AND ms.user_id IS NULL)
                            OR (ms.chat_type IN ('channel', 'dm') AND ms.user_id IS NULL)
                      )
                    ORDER BY
                        CASE
                            WHEN ms.user_id = tga.original_user_id THEN 1
                            WHEN ms.chat_type = 'group' AND ms.user_id IS NULL THEN 2
                            ELSE 3
                        END
                    LIMIT 1
                ) ms ON TRUE
                LEFT JOIN monitored_source_targets mst ON mst.source_id = ms.id
                WHERE tga.token_id = $1
                GROUP BY
                    tga.chat_id,
                    tga.original_message_id,
                    tga.first_seen_mc,
                    tga.last_alert_mc,
                    tga.original_user_id,
                    ms.id,
                    ms.user_id,
                    ms.is_enabled,
                    ms.sensitivity_pct,
                    ms.assigned_userbot_id,
                    ms.template_text,
                    ms.use_management_bot,
                    ms.chart_enabled,
                    ms.chart_bot_id,
                    ms.chart_mc_threshold
                """,
                token_id,
            )

            if not tracking_groups:
                logger.debug("[GROUP_ALERT_FIRE] No monitored groups for token %s, skipping", address[:8])
                return False

            settings_dict = await self.settings_model.get_gain_alert_settings()
            default_gain_threshold_pct = Decimal(str(settings_dict["gain_threshold_pct"]))
            global_template = await self.settings_model.get_gain_alert_template_text()
            chart_config = await self.settings_model.get_global_chart_settings()
            chart_threshold_override = chart_config.get("chart_threshold_override")
            chart_threshold_default = chart_config["chart_threshold_default"]

            candidate_threshold = chart_threshold_override or chart_threshold_default
            if not isinstance(candidate_threshold, Decimal):
                try:
                    candidate_threshold = Decimal(str(candidate_threshold))
                except (InvalidOperation, TypeError, ValueError):
                    logger.warning(
                        "[CHART_ALERT] Invalid global chart threshold %s; falling back to %s",
                        candidate_threshold,
                        DEFAULT_GLOBAL_CHART_THRESHOLD,
                    )
                    candidate_threshold = DEFAULT_GLOBAL_CHART_THRESHOLD

            if candidate_threshold <= 0:
                logger.warning(
                    "[CHART_ALERT] Non-positive global chart threshold %s; falling back to %s",
                    candidate_threshold,
                    DEFAULT_GLOBAL_CHART_THRESHOLD,
                )
                global_chart_threshold = DEFAULT_GLOBAL_CHART_THRESHOLD
            else:
                global_chart_threshold = candidate_threshold

            global_chart_bot_id = chart_config.get("chart_bot_id")

            workers_cache: Dict[int, Any] = {}
            template_cache: Dict[int, Optional[str]] = {}
            any_success = False

            for group in tracking_groups:
                chat_id = group["chat_id"]
                reply_to_msg_id = group["original_message_id"]
                first_seen_raw = group["first_seen_mc"]
                last_alert_mc = group["last_alert_mc"]

                if not first_seen_raw:
                    logger.debug("[GROUP_ALERT_FIRE] Chat %s missing first_seen_mc, skipping", chat_id)
                    continue

                try:
                    first_seen_mc = Decimal(str(first_seen_raw))
                except (ValueError, TypeError):
                    logger.debug(
                        "[GROUP_ALERT_FIRE] Chat %s has invalid first_seen_mc=%s, skipping",
                        chat_id,
                        first_seen_raw,
                    )
                    continue

                is_enabled = group["is_enabled"] if group["is_enabled"] is not None else True
                if not is_enabled:
                    logger.debug("[GROUP_ALERT_FIRE] Chat %s disabled for gain alerts, skipping", chat_id)
                    continue

                baseline_mc = Decimal(str(last_alert_mc)) if last_alert_mc else first_seen_mc
                if baseline_mc <= 0:
                    logger.debug(
                        "[GROUP_ALERT_FIRE] Chat %s baseline invalid (first_seen=%s last_alert=%s)",
                        chat_id,
                        first_seen_mc,
                        last_alert_mc,
                    )
                    continue

                custom_gain_pct = group["sensitivity_pct"]
                if custom_gain_pct is not None:
                    gain_threshold_pct = Decimal(str(custom_gain_pct))
                else:
                    gain_threshold_pct = default_gain_threshold_pct

                threshold_mc = compute_threshold(baseline_mc, gain_threshold_pct)
                if current_mc < threshold_mc:
                    continue

                use_management_bot = bool(group.get("use_management_bot")) if group.get("use_management_bot") is not None else False

                assigned_userbot_id = group["assigned_userbot_id"]
                executor = None

                if use_management_bot:
                    if not management_bot:
                        logger.warning(
                            "[GAIN_ALERT] Management bot unavailable for chat %s; falling back to userbot",
                            chat_id,
                        )
                        use_management_bot = False
                    else:
                        assigned_userbot_id = None

                if not use_management_bot:
                    if not userbot_manager:
                        logger.warning("[GAIN_ALERT] No userbot manager; cannot dispatch for %s", chat_id)
                        continue

                    worker = None
                    if assigned_userbot_id:
                        worker = userbot_manager.get_all_workers().get(assigned_userbot_id)
                        if not worker:
                            logger.warning(
                                "[GAIN_ALERT] Assigned userbot %s unavailable for chat %s; falling back",
                                assigned_userbot_id,
                                chat_id,
                            )
                    if not worker:
                        workers = userbot_manager.get_all_workers()
                        if not workers:
                            logger.error("[GAIN_ALERT] No active workers available to send alert")
                            continue
                        worker = next(iter(workers.values()))

                    worker_id = getattr(worker, "userbot_id", None)
                    if worker_id is None:
                        logger.error("[GAIN_ALERT] Worker missing userbot_id, skipping send")
                        continue

                    executor = workers_cache.get(worker_id)
                    if executor is None:
                        executor = getattr(worker, "call_executor", None)
                        workers_cache[worker_id] = executor

                chart_enabled_flag = bool(group.get("chart_enabled")) if group.get("chart_enabled") is not None else False
                chart_bot_id_value = group.get("chart_bot_id")
                if chart_bot_id_value is None:
                    chart_bot_id_value = global_chart_bot_id

                chart_threshold_raw = group.get("chart_mc_threshold")
                chart_threshold = global_chart_threshold
                if chart_threshold_raw is not None:
                    try:
                        chart_threshold = Decimal(str(chart_threshold_raw))
                    except (InvalidOperation, ValueError, TypeError):
                        logger.warning(
                            "[CHART_ALERT] Invalid chart threshold %s for chat %s; using global %s",
                            chart_threshold_raw,
                            chat_id,
                            global_chart_threshold,
                        )
                        chart_threshold = global_chart_threshold
                elif chart_threshold is None:
                    chart_threshold = DEFAULT_GLOBAL_CHART_THRESHOLD

                chart_bytes: Optional[bytes] = None
                if chart_enabled_flag and chart_bot_id_value:
                    if current_mc >= chart_threshold:
                        source_records = await self.source_model.get_by_chat(chat_id)
                        source_record = None
                        if source_records:
                            source_id = group.get("source_id")
                            if source_id is not None:
                                source_record = next(
                                    (record for record in source_records if record.get("id") == source_id),
                                    None,
                                )
                            if source_record is None:
                                for record in source_records:
                                    if (
                                        record.get("user_id") == group.get("original_user_id")
                                        or (record.get("user_id") is None and group.get("original_user_id") is None)
                                    ):
                                        source_record = record
                                        break

                        guardrails = await self.settings_model.resolve_chart_guardrails(source_record)

                        token_data = await db.fetchrow(
                            "SELECT * FROM tokens_tracked WHERE address = $1",
                            address,
                        )
                        if not token_data:
                            logger.warning("[CHART_GUARDRAIL] Token data not found for %s", address[:8])
                        else:
                            pair_data = None
                            try:
                                chain_id = self._normalise_chain_id(
                                    token_data.get("chain") or token_data.get("blockchain"),
                                    address,
                                )
                                pairs = await self.dex_client.fetch_token_pairs(
                                    address,
                                    chain_id=chain_id,
                                    use_cache=False,
                                )
                                if pairs:
                                    pair_data = self.dex_client._select_preferred_pair(pairs)
                            except Exception as exc:
                                logger.warning(
                                    "[CHART_GUARDRAIL] Error fetching pair data for %s: %s",
                                    address[:8],
                                    exc,
                                )

                            first_seen_at = token_data.get("first_seen_at")
                            first_seen_mc_for_guardrail = token_data.get("first_seen_mc", Decimal(0))

                            result = await evaluate_chart_guardrails(
                                token_data=token_data,
                                pair_data=pair_data,
                                guardrails=guardrails,
                                current_mc=current_mc,
                                first_seen_mc=first_seen_mc_for_guardrail,
                                first_seen_at=first_seen_at,
                                address=address,
                            )

                            if source_record and source_record.get("id"):
                                result_dict = {
                                    "passed": result.passed,
                                    "checks_passed": result.checks_passed,
                                    "checks_required": result.checks_required,
                                    "total_checks": len(result.checks),
                                    "checks": [
                                        {
                                            "name": check.name,
                                            "passed": check.passed,
                                            "actual_value": str(check.actual_value),
                                            "threshold_value": str(check.threshold_value),
                                            "reason": check.reason,
                                        }
                                        for check in result.checks
                                    ],
                                }
                                await db.execute(
                                    """
                                    UPDATE monitored_sources
                                    SET last_guardrail_result = $1::jsonb
                                    WHERE id = $2
                                    """,
                                    json.dumps(result_dict),
                                    source_record["id"],
                                )

                            if result.passed:
                                if chart_fetcher:
                                    try:
                                        logger.info(
                                            "[CHART_ALERT] Fetching chart for %s (chat %s, threshold=%s, current_mc=%s)",
                                            address[:8],
                                            chat_id,
                                            chart_threshold,
                                            current_mc,
                                        )
                                        chart_bytes = await chart_fetcher.fetch_chart_for_token(
                                            contract_address=address,
                                            chart_bot_id=int(chart_bot_id_value),
                                        )
                                    except Exception as exc:
                                        logger.error(
                                            "[CHART_ALERT] Error fetching chart for %s (chat %s): %s",
                                            address[:8],
                                            chat_id,
                                            exc,
                                            exc_info=True,
                                        )
                                        chart_bytes = None
                                else:
                                    logger.warning(
                                        "[CHART_ALERT] ChartFetcher unavailable; cannot fetch chart for chat %s",
                                        chat_id,
                                    )
                            else:
                                logger.debug(
                                    "[CHART_GUARDRAIL] Token %s failed guardrails for chat %s; skipping chart. %s",
                                    address[:8],
                                    chat_id,
                                    format_guardrail_summary(result),
                                )
                    else:
                        logger.debug(
                            "[CHART_ALERT] Current MC %s below chart threshold %s for chat %s; skipping chart",
                            current_mc,
                            chart_threshold,
                            chat_id,
                        )
                elif chart_enabled_flag:
                    logger.warning(
                        "[CHART_ALERT] Chart bot not configured for chat %s; skipping chart fetch",
                        chat_id,
                    )

                extra_targets = group.get("extra_targets") or []
                unique_targets = {chat_id}
                unique_targets.update(extra_targets)

                sent_success = False

                template_override = group.get("template_text")
                if (template_override is None or template_override == "") and chat_id not in template_cache:
                    try:
                        chat_records = await self.source_model.get_by_chat(chat_id)
                        template_cache[chat_id] = next(
                            (record.get("template_text") for record in chat_records if record.get("template_text")),
                            None,
                        )
                    except Exception as exc:
                        logger.debug("[GAIN_ALERT] Failed to lookup template for chat %s: %s", chat_id, exc)
                        template_cache[chat_id] = None

                if template_override in (None, ""):
                    template_override = template_cache.get(chat_id)

                template_candidate = template_override or global_template or DEFAULT_GAIN_ALERT_TEMPLATE

                missing = missing_required_placeholders(template_candidate)
                if missing:
                    logger.warning(
                        "[GAIN_ALERT] Template for chat %s missing placeholders %s; falling back",
                        chat_id,
                        ", ".join(sorted(missing)),
                    )
                    template_candidate = global_template or DEFAULT_GAIN_ALERT_TEMPLATE

                group_template_values = dict(template_values)
                group_template_values["first_market_cap"] = format_mc_shorthand(first_seen_mc)
                try:
                    multiplier_value = float(current_mc / first_seen_mc) if first_seen_mc > 0 else None
                except (ValueError, ZeroDivisionError):
                    multiplier_value = None
                if multiplier_value is not None:
                    group_template_values["multiplier"] = f"{multiplier_value:.1f}x"

                try:
                    alert_message = template_candidate.format(**group_template_values)
                except KeyError as exc:
                    logger.error(
                        "[GAIN_ALERT] Template formatting failed for chat %s (missing key: %s). Skipping.",
                        chat_id,
                        exc,
                        exc_info=True,
                    )
                    continue

                for target_chat in unique_targets:
                    try:
                        target_chat_int = int(target_chat)
                    except (TypeError, ValueError):
                        logger.debug("[GROUP_ALERT_FIRE] Invalid target chat id %s, skipping", target_chat)
                        continue

                    reply_id = reply_to_msg_id if target_chat_int == chat_id else None

                    alert_id = await db.fetchval(
                        """
                        INSERT INTO alert_queue
                        (token_id, token_address, alert_message, target_chat_id, reply_to_message_id, status)
                        VALUES ($1, $2, $3, $4, $5, 'pending')
                        RETURNING id
                        """,
                        token_id,
                        address,
                        alert_message,
                        target_chat_int,
                        reply_id,
                    )

                    if use_management_bot and management_bot:
                        result = await management_bot.send_message(
                            target_chat_int,
                            alert_message,
                            reply_to_message_id=reply_id,
                            photo_bytes=chart_bytes,
                        )
                    else:
                        if executor is None:
                            logger.error("[GAIN_ALERT] Executor missing for chat %s; skipping send", chat_id)
                            continue
                        result = await executor.send_alert_message(
                            target_chat_id=target_chat_int,
                            message=alert_message,
                            reply_to_message_id=reply_id,
                            photo_bytes=chart_bytes,
                        )

                    if result.get("success"):
                        sent_success = True
                        any_success = True
                        logger.info(
                            "[GROUP_ALERT_FIRE] Sent to chat %s, msg_id=%s",
                            target_chat_int,
                            result.get("message_id"),
                        )
                        log_event(
                            logger,
                            "gain_alert_dispatched",
                            token_address=address,
                            target_chat_id=target_chat_int,
                            message_id=result.get("message_id"),
                        )
                        await db.execute(
                            """
                            UPDATE alert_queue
                            SET status='sent', attempt_count=1, last_attempt_at=NOW()
                            WHERE id=$1
                            """,
                            alert_id,
                        )
                    else:
                        error_text = result.get("error") or "Unknown error"
                        logger.error(
                            "[GROUP_ALERT_FIRE] Failed to send to chat %s: %s",
                            target_chat_int,
                            error_text,
                        )
                        await db.execute(
                            """
                            UPDATE alert_queue
                            SET status='failed', error=$2, attempt_count=1, last_attempt_at=NOW()
                            WHERE id=$1
                            """,
                            alert_id,
                            error_text,
                        )

                if sent_success:
                    await db.execute(
                        """
                        UPDATE token_group_alerts
                        SET last_alert_mc = $1
                        WHERE token_id = $2 AND chat_id = $3
                        """,
                        current_mc,
                        token_id,
                        chat_id,
                    )

            return any_success
        except Exception as exc:
            logger.error("Error dispatching gain alert for %s: %s", address[:8], exc, exc_info=True)
            return False

    @staticmethod
    def _normalise_chain_id(chain_id: Optional[str], address: str) -> str:
        if not chain_id:
            if address.lower().startswith("0x") and len(address) == 42:
                candidate = "bsc"
            else:
                candidate = "solana"
        else:
            candidate = str(chain_id).lower()

        if candidate in ("sol", "solana", "solana-mainnet"):
            return "solana"
        if candidate in ("bsc", "bnb", "bep20", "binance"):
            return "bsc"
        return candidate
