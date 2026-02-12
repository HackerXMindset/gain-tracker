# Future Features

Ideas for future implementation.

---

## 1. Smart Exit Alerts

**Status:** Considering

**Description:**
Detect when a token dumps after pumping and alert users to consider exiting. Helps users actually take profits instead of riding gains back down.

**How it works:**
- Already tracking `peak_mc` for each token
- During polling, calculate: `drop_pct = (peak_mc - current_mc) / peak_mc * 100`
- Alert at configurable thresholds (e.g., -30%, -50%, -70% from ATH)
- Only trigger after token has hit minimum gain first (e.g., 2x+)

**Requirements:**
- Exit threshold settings (global + per-source override)
- Track which exit levels already alerted per token (avoid spam)
- New alert template for exit warnings
- Minimum gain requirement before exit alerts activate

**Example flow:**
1. TOKEN hits 10x peak ($100k MC)
2. Drops to $70k → "TOKEN -30% from ATH"
3. Drops to $50k → "TOKEN -50% from ATH"
4. Drops to $30k → "TOKEN -70% from ATH, consider exit"

**Template example:**
```
⚠️ {ticker} down {drop_pct}% from peak
Peak: {peak_mc} → Now: {current_mc}
```

**DB changes needed:**
- `tokens_tracked.last_exit_alert_level` - track highest exit alert sent (30/50/70)
- Settings: `exit_alert_enabled`, `exit_alert_thresholds` (JSON array)
- Per-source: `exit_alerts_enabled` override

---

## 2. Bulk Stop by Age (`/stop_ca`)

**Status:** Considering

**Description:**
Stop tracking all tokens older than a specified timeframe. Useful for cleaning up old tokens that are no longer relevant.

**Command:**
```
/stop_ca {timeframe}
```

**Examples:**
```
/stop_ca 1d      - Stop all tokens older than 1 day
/stop_ca 6h      - Stop all tokens older than 6 hours
/stop_ca 12h     - Stop all tokens older than 12 hours
/stop_ca 3d      - Stop all tokens older than 3 days
/stop_ca 1w      - Stop all tokens older than 1 week
```

**Flow:**
1. User runs `/stop_ca 1d`
2. Bot queries: `SELECT COUNT(*) FROM tokens_tracked WHERE first_seen_at < NOW() - INTERVAL '1 day' AND status = 'active'`
3. Bot replies: "⚠️ This will stop 47 tokens older than 1 day. [Confirm] [Cancel]"
4. User clicks Confirm
5. Bot executes: `UPDATE tokens_tracked SET status = 'stopped', stop_reason = 'bulk_age_stop' WHERE ...`
6. Bot replies: "✅ Stopped 47 tokens"

**Timeframe parsing:**
- Use same logic as hold_timeframes
- Support: `5m`, `30m`, `1h`, `6h`, `12h`, `24h`, `1d`, `2d`, `3d`, `7d`, `1w`, `2w`, `30d`, `1mo`

**Implementation:**
```python
async def cmd_stop_ca(message: types.Message, state: FSMContext) -> None:
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /stop_ca {timeframe}\nExample: /stop_ca 1d")
        return

    timeframe = parts[1]
    seconds = parse_timeframe_to_seconds(timeframe)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    count = await db.fetchval(
        "SELECT COUNT(*) FROM tokens_tracked WHERE first_seen_at < $1 AND status = 'active'",
        cutoff
    )

    if count == 0:
        await message.answer(f"No active tokens older than {timeframe}")
        return

    # Store in state for confirmation
    await state.update_data(stop_cutoff=cutoff, stop_count=count, stop_timeframe=timeframe)
    await state.set_state(StopCaStates.confirming)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data="stop_ca:confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="stop_ca:cancel"),
        ]
    ])
    await message.answer(
        f"⚠️ This will stop {count} tokens older than {timeframe}.\n\nConfirm?",
        reply_markup=keyboard
    )
```

**DB changes:** None (uses existing tokens_tracked table)

---
