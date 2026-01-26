---
task: h-implement-analytics-phase1
branch: feature/analytics-phase1
status: in-progress
created: 2026-01-25
modules: [scheduler, models, migrations, db]
---

# Analytics Phase 1-6: Complete Analytics System

## Problem/Goal
Implement complete analytics infrastructure to track token performance milestones (2x, 5x, 10x, 100x) automatically during token polling. Implement MC history tracking for investment simulator time-based hold strategies. Build the stats calculation engine to compute win rates, averages, and leaderboards. Add UI stats button to source detail view. Implement /stats, /top, /patterns, and /invest commands for comprehensive analytics access. Add time pattern analysis to identify best hours and days. Add investment simulator to calculate hypothetical P&L scenarios. This implements all 6 phases of the analytics features plan defined in plan.md.

## Success Criteria

### Phase 1: Milestone Tracking
- [x] Migration 008_analytics_phase1.sql created and applies successfully
- [x] token_milestones table created with proper indexes and constraints
- [x] source_stats and hourly_patterns tables created (schema only for future phases)
- [x] tokens_tracked table has peak_reached_at and caller_user_id columns
- [x] Milestone detection logic added to scheduler/dex_service.py
- [x] TokenModel has update_peak_reached_at() method
- [x] AnalyticsModel created with milestone query methods
- [ ] Milestones recorded automatically as tokens hit 2x/5x/10x/100x multipliers (needs testing)
- [ ] No errors in scheduler logs during milestone detection (needs testing)
- [ ] Manual testing confirms milestones are recorded correctly

### Phase 1.5: MC History
- [x] Migration 009_mc_history.sql created
- [x] token_mc_history table created with indexes
- [x] hold_timeframes table created with seed data
- [x] MC history recording added to polling loop
- [x] AnalyticsModel has record_mc_history() method
- [x] AnalyticsModel has get_mc_at_time() and get_mc_after_duration() helpers
- [x] AnalyticsModel has hold_timeframes management methods
- [ ] MC history snapshots recorded on every poll (needs testing)
- [ ] Query helpers return accurate historical MC data (needs testing)

### Phase 2: Stats Calculation Engine
- [x] AnalyticsModel has calculate_source_stats() method
- [x] AnalyticsModel has get_cached_stats() method
- [x] AnalyticsModel has refresh_stats_cache() method
- [x] AnalyticsModel has get_top_sources() leaderboard method
- [x] StatsRefreshService created for background refresh
- [x] Stats refresh runs hourly for all sources
- [ ] Stats calculation returns accurate win rates (needs testing)
- [ ] Cached stats are populated and refreshed (needs testing)
- [ ] Leaderboard query works correctly (needs testing)

### Phase 3: UI - Source Stats Button
- [x] AnalyticsModel imported in GainAlertsHandler
- [x] analytics_model instance created in handler __init__
- [x] Stats button added to source detail keyboard
- [x] show_source_stats() handler method created
- [x] _format_source_stats() helper method for HTML formatting
- [x] _build_stats_keyboard() helper for timeframe selection
- [x] Router callback registered for stats view
- [ ] Stats display shows correct data (needs testing)
- [ ] Timeframe switching works (needs testing)

### Phase 4: Commands - /stats, /top
- [x] AnalyticsCommandsHandler class created
- [x] cmd_stats() method with flexible parsing (chat_id, user_id, timeframe)
- [x] cmd_top() method for leaderboard
- [x] Helper methods: _parse_chat_user_id(), _parse_timeframe(), _format_stats(), _format_leaderboard()
- [x] Handler registered in admin_bot.py
- [x] Commands registered: /stats, /top, /leaderboard
- [ ] /stats command works with all formats (needs testing)
- [ ] /top command shows leaderboard (needs testing)

### Phase 5: Time Pattern Analysis
- [x] AnalyticsModel has analyze_time_patterns() method
- [x] cmd_patterns() method implemented with chat_id and timeframe parsing
- [x] _format_patterns() helper method for HTML formatting with visual bars
- [x] _make_bar() helper for creating visual percentage bars
- [x] /patterns command registered in admin_bot.py (both run_admin_bot and create_admin_dispatcher)
- [ ] /patterns command displays hourly and daily breakdowns (needs testing)
- [ ] Best hour (UTC and IST) and best day identified correctly (needs testing)


### Phase 6: Investment Simulator
- [x] AnalyticsModel has simulate_investment() method
- [x] AnalyticsModel has _get_tokens_for_simulation() helper
- [x] AnalyticsModel has _get_exit_mc() for hold strategy calculation
- [x] AnalyticsModel has _parse_duration() for time parsing
- [x] cmd_invest() method implemented with flexible parsing
- [x] _format_investment_results() helper for HTML formatting
- [x] /invest command registered in admin_bot.py (both functions)
- [x] Command supports multiple hold strategies (peak, current, time-based)
- [x] Command supports source filtering and timeframes
- [ ] /invest command calculates accurate P&L (needs testing)
- [ ] Top/worst performers displayed correctly (needs testing)
## Context Files
- @scheduler/dex_service.py:185-198
- @models/token.py
- @migrations/*.sql
- @db/database.py
- @plan.md
This implements all 6 phases of the analytics implementation plan. All core functionality is complete and ready for testing.
## User Notes
This is Phase 1 of a 6-phase analytics implementation plan.

Key design decisions:
- Use INSERT ... ON CONFLICT DO NOTHING for efficient milestone deduplication
- Piggyback on existing polling (zero additional API calls)
- Track peak_reached_at only when peak_mc actually increases
- Create schema for future phases now to avoid multiple migrations

## Work Log
- [2026-01-25] Task created, plan mode exploration completed
- [2026-01-25] Starting implementation - Phase 1
- [2026-01-25] Created migration 008_analytics_phase1.sql with all 3 tables and tokens_tracked alterations
- [2026-01-25] Added update_peak_reached_at() method to TokenModel
- [2026-01-25] Created AnalyticsModel with milestone query methods
- [2026-01-25] Added _check_and_record_milestones() method to DexService
- [2026-01-25] Integrated milestone detection into polling loop (after peak_mc update)
- [2026-01-25] Exported AnalyticsModel from models/__init__.py
- [2026-01-25] Created feature/analytics-phase1 branch
- [2026-01-25] Fixed code review issues: consistent DB access via AnalyticsModel, improved log message
- [2026-01-25] Starting implementation - Phase 1.5
- [2026-01-25] Created migration 009_mc_history.sql with token_mc_history and hold_timeframes tables
- [2026-01-25] Added MC history methods to AnalyticsModel (record, query helpers, timeframe management)
- [2026-01-25] Integrated MC history recording into polling loop (records on every poll)
- [2026-01-25] Phase 1 & 1.5 implementation complete, ready for testing
- [2026-01-25] Starting implementation - Phase 2
- [2026-01-25] Added calculate_source_stats() to AnalyticsModel with win rate calculations
- [2026-01-25] Added get_cached_stats() and refresh_stats_cache() for stats caching
- [2026-01-25] Added get_top_sources() leaderboard query
- [2026-01-25] Created StatsRefreshService for background stats refresh (hourly)
- [2026-01-25] Added timezone import to AnalyticsModel
- [2026-01-25] Phase 1, 1.5 & 2 implementation complete, ready for testing
- [2026-01-25] Fixed Issue 1: Changed calculate_source_stats to use token_group_alerts instead of non-existent token_call_history
- [2026-01-25] Fixed Issue 2: Added missing columns to source_stats table (period_start, period_end, avg_time_to_peak_seconds, updated_at)
- [2026-01-25] Fixed Issue 3: Updated hold_timeframes regex to allow 'w' suffix for weeks
- [2026-01-25] All code review issues resolved
- [2026-01-25] Starting implementation - Phase 3
- [2026-01-25] Added AnalyticsModel import and instance to GainAlertsHandler
- [2026-01-25] Added "📈 Stats" button to source detail keyboard
- [2026-01-25] Implemented show_source_stats() handler method with timeframe support
- [2026-01-25] Created _format_source_stats() to format stats as HTML (win rates, avg peak, time to peak, best/worst)
- [2026-01-25] Created _build_stats_keyboard() with 1h/24h/7d/30d timeframe buttons
- [2026-01-25] Registered stats callback in router with timeframe parsing
- [2026-01-25] Phase 1, 1.5, 2 & 3 implementation complete, ready for testing
- [2026-01-25] Starting implementation - Phase 4
- [2026-01-25] Created AnalyticsCommandsHandler in ui/handlers/analytics_commands.py
- [2026-01-25] Implemented cmd_stats() with support for chat_id, user_id, and multiple timeframe formats
- [2026-01-25] Implemented cmd_top() for leaderboard display
- [2026-01-25] Created helper methods for parsing and formatting
- [2026-01-25] Imported AnalyticsCommandsHandler in admin_bot.py
- [2026-01-25] Registered analytics_handler instance
- [2026-01-25] Registered /stats and /top commands with admin auth
- [2026-01-25] Phase 1, 1.5, 2, 3 & 4 implementation complete, ready for testing
- [2026-01-25] Starting implementation - Phase 5
- [2026-01-25] Added analyze_time_patterns() to AnalyticsModel with hourly and daily analysis
- [2026-01-25] Implemented cmd_patterns() in AnalyticsCommandsHandler with chat_id and timeframe parsing
- [2026-01-25] Created _format_patterns() helper for HTML formatting with visual bars
- [2026-01-25] Created _make_bar() helper for creating visual percentage bars (█ for filled, ░ for empty)
- [2026-01-25] Registered /patterns command in both run_admin_bot() and create_admin_dispatcher() functions
- [2026-01-25] Phase 1, 1.5, 2, 3, 4 & 5 implementation complete, ready for testing- [2026-01-25] Starting implementation - Phase 6
- [2026-01-25] Added simulate_investment() to AnalyticsModel with P&L calculation engine
- [2026-01-25] Added _get_tokens_for_simulation() to fetch tokens by timeframe or count
- [2026-01-25] Added _get_exit_mc() to determine exit price based on hold strategy (peak/current/time-based)
- [2026-01-25] Added _parse_duration() helper for parsing time durations (1h, 6h, 24h, etc.)
- [2026-01-25] Implemented cmd_invest() in AnalyticsCommandsHandler with flexible parsing
- [2026-01-25] Created _format_investment_results() helper for HTML P&L formatting
- [2026-01-25] Registered /invest command in both run_admin_bot() and create_admin_dispatcher()
- [2026-01-25] Added command aliases: /invest and /sim
- [2026-01-25] Phase 1, 1.5, 2, 3, 4, 5 & 6 implementation complete - ALL PHASES DONE, ready for testing
