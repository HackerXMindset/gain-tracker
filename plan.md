# Analytics Features Implementation Plan

## Overview

Three major analytics features:
1. **Caller Performance Dashboard** - Win rates, stats per source
2. **Time Pattern Analysis** - Hourly/daily performance patterns
3. **Hypothetical Investment Calculator** - Simulate P&L scenarios

---

## Phase 1: Database Schema & Data Collection

**Goal:** Set up tables and start collecting analytics data.

### 1.1 New Tables

```sql
-- Track each token's performance milestones
CREATE TABLE token_milestones (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    milestone TEXT NOT NULL,  -- '2x', '5x', '10x', '100x'
    reached_at TIMESTAMPTZ NOT NULL,
    mc_at_milestone NUMERIC,
    time_to_reach_seconds INT,  -- seconds from first_seen
    UNIQUE(token_id, milestone)
);

-- Aggregated stats per source (cached, updated periodically)
CREATE TABLE source_stats (
    id BIGSERIAL PRIMARY KEY,
    source_chat_id BIGINT NOT NULL,
    user_id BIGINT,  -- NULL for channel, or specific user for group sub-stats
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    total_calls INT DEFAULT 0,
    hits_2x INT DEFAULT 0,
    hits_5x INT DEFAULT 0,
    hits_10x INT DEFAULT 0,
    hits_100x INT DEFAULT 0,
    avg_peak_multiplier NUMERIC,
    avg_time_to_peak_seconds INT,
    best_call_token_id BIGINT,
    best_call_multiplier NUMERIC,
    worst_call_token_id BIGINT,
    worst_call_multiplier NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_chat_id, user_id, period_start, period_end)
);

-- Hourly performance patterns
CREATE TABLE hourly_patterns (
    id BIGSERIAL PRIMARY KEY,
    source_chat_id BIGINT,  -- NULL for global
    hour_utc INT NOT NULL CHECK (hour_utc >= 0 AND hour_utc < 24),
    day_of_week INT CHECK (day_of_week >= 0 AND day_of_week < 7),  -- 0=Monday
    total_calls INT DEFAULT 0,
    hits_2x INT DEFAULT 0,
    avg_multiplier NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 1.2 Modify Existing Tables

```sql
-- Add to tokens_tracked
ALTER TABLE tokens_tracked ADD COLUMN IF NOT EXISTS peak_reached_at TIMESTAMPTZ;
ALTER TABLE tokens_tracked ADD COLUMN IF NOT EXISTS caller_user_id BIGINT;
```

### 1.3 Data Collection Logic

- On each poll: check if new milestone reached (2x/5x/10x/100x from first_seen_mc)
- Record milestone with timestamp
- Update peak_reached_at when new peak_mc set

**Files to modify:**
- `scheduler/dex_service.py` - Add milestone detection in poll loop
- `models/token.py` - Add milestone recording methods

---

## Phase 2: Stats Calculation Engine

**Goal:** Build the calculation logic for all stats.

### 2.1 New Model: `models/analytics.py`

```python
class AnalyticsModel(BaseModel):
    # Source stats
    async def calculate_source_stats(self, chat_id: int, user_id: Optional[int],
                                      start: datetime, end: datetime) -> Dict
    async def get_cached_stats(self, chat_id: int, period: str) -> Optional[Dict]
    async def refresh_stats_cache(self, chat_id: int, period: str) -> None

    # Time patterns
    async def get_hourly_patterns(self, chat_id: Optional[int]) -> List[Dict]
    async def get_day_patterns(self, chat_id: Optional[int]) -> List[Dict]

    # Leaderboard
    async def get_top_sources(self, period: str, limit: int = 10) -> List[Dict]

    # Investment simulation
    async def simulate_investment(self, amount: float, chat_id: Optional[int],
                                   token_count: Optional[int], timeframe: str,
                                   hold_strategy: str) -> Dict
```

### 2.2 Stats Calculation Logic

**Win rate calculation:**
```python
win_rate_2x = hits_2x / total_calls * 100
win_rate_5x = hits_5x / total_calls * 100
# etc.
```

**Time to peak:**
```python
avg_time_to_peak = AVG(peak_reached_at - first_seen_at)
```

**Best/worst calls:**
```python
best = MAX(peak_mc / first_seen_mc)
worst = MIN(peak_mc / first_seen_mc)  # or last_mc for still active
```

### 2.3 Background Stats Refresh

- Cron job or scheduler task to refresh cached stats
- Refresh intervals: 1h for daily stats, 6h for weekly, 24h for monthly

**Files to create:**
- `models/analytics.py`
- `scheduler/stats_refresh.py`

---

## Phase 3: UI - Source Stats Button

**Goal:** Add stats button to source detail view.

### 3.1 Handler Updates

**In `ui/handlers/gain_alerts.py`:**

```python
async def show_source_stats(self, query: CallbackQuery, chat_id: int) -> None:
    """Show stats for a monitored source (default: last 24h)"""
    stats = await self.analytics_model.get_cached_stats(chat_id, "24h")
    text = self._format_source_stats(stats)
    keyboard = self._build_stats_keyboard(chat_id)
    await query.message.edit_text(text, reply_markup=keyboard)

def _format_source_stats(self, stats: Dict) -> str:
    """Format stats as text with IST + UTC times"""
    # Total calls, win rates at 2x/5x/10x/100x
    # Avg time to peak, best/worst call
    # Per-user breakdown for groups
```

### 3.2 Keyboard Updates

Add to `_build_source_detail_keyboard()`:
```python
rows.append([
    InlineKeyboardButton(
        text="📊 Stats",
        callback_data=f"gain_alerts:view:stats:{chat_id}",
    )
])
```

Stats view keyboard - timeframe buttons: 1h, 24h, 7d, 30d + Back

### 3.3 Router Updates

Register callback patterns:
- `gain_alerts:view:stats:{chat_id}`
- `gain_alerts:view:stats:{chat_id}:{timeframe}`

**Files to modify:**
- `ui/handlers/gain_alerts.py`
- `ui/routers/gain_alerts.py`

---

## Phase 4: Commands - /stats, /top

**Goal:** Implement command-based access to stats.

### 4.1 `/stats` Command

**Usage formats:**

```
# Channel stats
/stats {chat_id} {timeframe}
/stats -1001234567890 24h
/stats -1001234567890 7d

# Group stats (aggregate of all users)
/stats -1009876543210 24h

# Specific user in group
/stats {chat_id} {timeframe} user:{user_id}
/stats -1009876543210 24h user:123456789

# Shorthand for user in group
/stats {chat_id}:{user_id} {timeframe}
/stats -1009876543210:123456789 7d
```

**Timeframes:** `1h`, `6h`, `24h`, `2d`, `7d`, `14d`, `30d`, `1w`, `1mo`

```python
async def cmd_stats(message: types.Message) -> None:
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer(
            "📊 <b>Stats Command</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/stats {chat_id} {timeframe}</code>\n"
            "<code>/stats {chat_id} {timeframe} user:{user_id}</code>\n"
            "<code>/stats {chat_id}:{user_id} {timeframe}</code>\n\n"
            "<b>Timeframes:</b> 1h, 6h, 24h, 2d, 7d, 14d, 30d, 1w, 1mo\n\n"
            "<b>Examples:</b>\n"
            "• <code>/stats -1001234567890 24h</code>\n"
            "• <code>/stats -1009876543210 7d user:123456789</code>\n"
            "• <code>/stats -1009876543210:123456789 7d</code>",
            parse_mode="HTML"
        )
        return

    # Parse chat_id and optional user_id
    chat_id, user_id = parse_chat_user_id(parts[1])
    timeframe = "24h"

    for part in parts[2:]:
        if part.startswith("user:"):
            user_id = int(part.split(":")[1])
        elif part in VALID_TIMEFRAMES:
            timeframe = part

    stats = await analytics_model.calculate_source_stats(
        chat_id, user_id,
        start=parse_timeframe(timeframe),
        end=datetime.now()
    )

    text = format_stats_text(stats, timeframe, user_id)
    await message.answer(text, parse_mode="HTML")


def parse_chat_user_id(raw: str) -> Tuple[int, Optional[int]]:
    """Parse 'chat_id' or 'chat_id:user_id' format"""
    if ":" in raw:
        parts = raw.split(":")
        return int(parts[0]), int(parts[1])
    return int(raw), None
```

### 4.2 `/top` Command

**Usage:** `/top {timeframe}` (default: 7d)

```python
async def cmd_top(message: types.Message) -> None:
    parts = message.text.split()
    timeframe = parts[1] if len(parts) > 1 else "7d"

    leaderboard = await analytics_model.get_top_sources(timeframe, limit=10)
    text = format_leaderboard(leaderboard, timeframe)
    await message.answer(text, parse_mode="HTML")
```

**Output format:**
```
🏆 Top Callers (7d)

1. Channel A - 67% hit 2x (45 calls)
2. Channel B - 58% hit 2x (32 calls)
3. Group C - 52% hit 2x (28 calls)
...
```

### 4.3 Register Commands

**In `admin_bot.py`:**
```python
dp.message.register(cmd_stats, Command(commands=["stats"]), ...)
dp.message.register(cmd_top, Command(commands=["top", "leaderboard"]), ...)
```

---

## Phase 5: Time Pattern Analysis

**Goal:** Show hourly/daily performance patterns.

### 5.1 Pattern Calculation

```python
async def analyze_time_patterns(self, chat_id: Optional[int] = None) -> Dict:
    return {
        "hourly": [
            {"hour_utc": 0, "hour_ist": 5.5, "calls": 45, "win_rate_2x": 34.2},
            {"hour_utc": 1, "hour_ist": 6.5, "calls": 23, "win_rate_2x": 48.1},
            # ...
        ],
        "daily": [
            {"day": "Monday", "calls": 156, "win_rate_2x": 42.3, "avg_mult": 3.2},
            # ...
        ],
        "best_hour_utc": 14,
        "best_hour_ist": 19.5,
        "best_day": "Wednesday",
    }
```

### 5.2 Display Format

```
📈 Time Patterns (Channel X)

Best hour: 14:00 UTC / 19:30 IST (52% hit 2x)
Best day: Wednesday (48% hit 2x)

Hourly breakdown:
00-03 UTC: ▁▁▂ 23% avg
04-07 UTC: ▂▃▄ 31% avg
08-11 UTC: ▅▆▇ 47% avg
12-15 UTC: ▇█▇ 52% avg  ← peak
16-19 UTC: ▆▅▄ 41% avg
20-23 UTC: ▃▂▂ 28% avg

Daily breakdown:
Mon: 42% | Tue: 38% | Wed: 48% ← best
Thu: 44% | Fri: 35% | Sat: 29% | Sun: 25%
```

### 5.3 Access Points

- Button in stats view: "📈 Time Patterns"
- Command: `/patterns {chat_id}`

**Files to modify:**
- `models/analytics.py`
- `ui/handlers/gain_alerts.py`

---

## Phase 6: Investment Simulator

**Goal:** `/invest` command with interactive button flow.

### 6.1 Command Entry

```python
async def cmd_invest(message: types.Message) -> None:
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer("Usage: /invest {amount}\nExample: /invest 100")
        return

    amount = parse_amount(parts[1])  # handles "$100", "100", "100$"
    keyboard = build_invest_options_keyboard(amount)
    await message.answer(
        f"💰 Simulating ${amount} investment\n\nChoose options:",
        reply_markup=keyboard
    )
```

### 6.2 Interactive Flow (Buttons)

**Step 1:** Amount entered via command

**Step 2:** Source selection
- "All Sources" (default)
- "Select Source..." → paginated list

**Step 3:** Timeframe selection
- "Last 24h" (default)
- "Last 7d", "Last 30d"
- "Last N tokens..." → ask for number

**Step 4:** Hold strategy
- "To Peak" (default)
- "1h", "6h", "24h"
- "Still Holding" (current price)
- "Custom..."

**Step 5:** Allocation
- "Equal Split" (default)
- "Weighted by Caller Score"

### 6.3 Calculation Engine

```python
async def simulate_investment(
    self,
    amount: float,
    chat_id: Optional[int],  # None = all sources
    token_filter: Dict,  # {"count": 10} or {"timeframe": "24h"}
    hold_strategy: str,  # "peak", "1h", "6h", "24h", "current"
    allocation: str,  # "equal" or "weighted"
) -> Dict:

    tokens = await self._get_tokens_for_simulation(chat_id, token_filter)

    if allocation == "equal":
        per_token = amount / len(tokens)
    else:
        per_token = self._weighted_allocation(tokens, amount)

    results = []
    for token in tokens:
        entry_mc = token["first_seen_mc"]

        if hold_strategy == "peak":
            exit_mc = token["peak_mc"]
        elif hold_strategy == "current":
            exit_mc = token["last_mc"]
        else:
            exit_mc = await self._get_mc_at_time(token, hold_strategy)

        multiplier = exit_mc / entry_mc
        pnl = per_token * multiplier - per_token

        results.append({
            "token": token,
            "multiplier": multiplier,
            "invested": per_token,
            "final_value": per_token * multiplier,
            "pnl": pnl,
        })

    results.sort(key=lambda x: x["pnl"], reverse=True)

    return {
        "top_15": results[:15],
        "total_tokens": len(results),
        "total_invested": amount,
        "total_final_value": sum(r["final_value"] for r in results),
        "total_pnl": sum(r["pnl"] for r in results),
        "winners": len([r for r in results if r["pnl"] > 0]),
        "losers": len([r for r in results if r["pnl"] <= 0]),
    }
```

### 6.4 Output Format

```
💰 Investment Simulation Results

Settings:
• Amount: $100
• Source: All Sources
• Period: Last 24h (47 tokens)
• Hold: To Peak
• Split: Equal ($2.13/token)

📊 Summary:
• Final Value: $847.23
• Total P&L: +$747.23 (+747%)
• Winners: 31 | Losers: 16

🏆 Top 15 Performers:
1. PEPE: $2.13 → $42.60 (+1900%)
2. DOGE: $2.13 → $21.30 (+900%)
3. SHIB: $2.13 → $12.78 (+500%)
...

❌ Biggest Losers:
1. RUG: $2.13 → $0.02 (-99%)
2. SCAM: $2.13 → $0.21 (-90%)
```

### 6.5 FSM States

```python
class InvestStates(StatesGroup):
    selecting_source = State()
    selecting_timeframe = State()
    selecting_hold = State()
    selecting_allocation = State()
    entering_custom_tokens = State()
    entering_custom_hold = State()
```

**Files to create/modify:**
- `ui/states.py` - Add InvestStates
- `ui/handlers/invest.py` - New handler
- `ui/routers/invest.py` - New router
- `admin_bot.py` - Register command

---

## Summary

| Phase | Deliverable | Complexity |
|-------|-------------|------------|
| 1 | DB schema + data collection | Medium |
| 2 | Stats calculation engine | Medium |
| 3 | UI stats button | Low |
| 4 | /stats, /top commands | Low |
| 5 | Time pattern analysis | Medium |
| 6 | Investment simulator | High |

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6

Phase 1 & 2 are foundational. Phases 3-5 can be parallelized after. Phase 6 is standalone but benefits from Phase 2's engine.
