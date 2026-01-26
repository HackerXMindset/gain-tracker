# OKX Monitoring Integration Plan (Root App)

## Phase 1 — Confirm behavior and scope
- Lock requirements: Solana‑only OKX API, Jupiter‑first for first‑seen + timeframe snapshots + pre‑alert, OKX‑first for ongoing monitoring, DexScreener last fallback.
- Identify all touchpoints for market‑cap fetch in root app (token detection, scheduler polling, alert dispatch, analytics snapshots).

## Phase 2 — Add OKX API client (root services)
- Create `services/okx_market_api.py` to call OKX endpoint and parse market cap, price, liquidity, ticker.
- Add lightweight caching + timeout similar to existing services.
- Expose `get_okx_service()` singleton in `services/__init__.py`.

## Phase 3 — Wire fetch order by context
- **New token detection** (`userbot/token_monitor.py`): Jupiter → OKX → DexScreener.
- **Timeframe snapshots** (MC history used by `/invest`): Jupiter → OKX → DexScreener.
- **Ongoing monitoring** (`scheduler/dex_service.py`): OKX → DexScreener (no Jupiter).
- **Pre‑alert validation** (if extra fetch before alert): Jupiter → OKX → DexScreener.

## Phase 4 — Data consistency & history
- Ensure MC snapshots are still recorded from the selected source.
- Preserve existing validation (min/max MC bounds).
- Add structured logging of which source supplied the MC for traceability.

## Phase 5 — Tests & safe rollout
- Add unit tests or minimal integration tests for OKX parsing and fallback order.
- Verify `/invest` timeframe snapshots still populate with Jupiter‑first.
- Confirm no regressions in alert triggering and stop‑loss behavior.

## Phase 6 — Docs & ops
- Update `RUNBOOK.md` and `.env.sample` only if new settings are added.
- Document new data source order and fallback behavior in README/RUNBOOK.

