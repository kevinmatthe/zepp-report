# Period comparison implementation plan

Goal: Make current-versus-baseline changes easy to scan while reducing card height.

Approved design: retain the existing palette, show a prominent neutral change badge beside each value, a separate baseline value and compact coverage row, and dashed baseline curves with explicit dates. Missing data remains missing and today's unfinished data is excluded from comparisons.

1. Add regression tests for baseline series, zero/missing values, unequal periods and weekly alignment.
2. Extend analytics responses with baseline rows aligned to the current period's day positions and aggregation boundaries, retaining original dates.
3. Update metric cards and responsive styles; expose statistical details through keyboard/touch accessible disclosure.
4. Add dashed baseline series and dated period legends; preserve gaps and show actual baseline dates in tooltips.
5. Build and run analytics and browser tests, inspect 375/414/768/1024/1440 layouts, and refresh README screenshots.

Files: `zepp_report/analytics.py`, `zepp_report/static/metric-cards.js`, `zepp_report/static/trend-charts.js`, `zepp_report/static/style.css`, `zepp_report/static/app.js`, analytics and UI tests, README screenshot.
