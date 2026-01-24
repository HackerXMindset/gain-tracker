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
