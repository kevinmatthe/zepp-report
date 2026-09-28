# Health comparison beta

Approved scope: independent `/beta` page; preserve the existing homepage. Equal-weight sleep, heart rate, blood oxygen and steps. Period selector supports previous period, prior year and no comparison. Sleep exposes deep-sleep duration and deep-sleep share with explicit percentage-point differences.

Implementation:
1. Test route isolation and pure aggregation (paired-night weighted deep-sleep share, missing/zero values, incomplete today).
2. Add separate HTML, CSS, JS bundle and a `/beta` route, sharing only existing authenticated APIs.
3. Fetch full baseline daily data using the existing comparison range; never derive whole-period summaries from clipped aligned curves.
4. Render equal-weight cards and chart panels, explicit date ranges, coverage and current/baseline/difference tables. Preserve gaps and distinguish percent from percentage points.
5. Validate responsive layouts, login/session expiry, compare switching, race handling, empty data and the existing UI. Deploy alongside `/` and verify both.

Validation: 136 backend tests pass; existing UI and beta browser suites pass at 375/414/768/1024/1440 widths. Checked weighted sleep ratios, zeros/missing data, unfinished days, comparison modes, late responses, session expiry and route isolation.
