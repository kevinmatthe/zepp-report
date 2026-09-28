# Fine-grained health detail

The user requested all collected fine-grained observations to be accessible in Web UI or Grafana, especially minute steps, while retaining the approved trend-first layout.

## Display

Keep aggregate trends and five-minute typical-day comparisons. Add a separate selected-day original-resolution chart and paginated exact timestamp table, with steps, heart rate, stress, blood oxygen and timestamped training/load events. Use step bars and unconnected observation marks; provide time zoom and retain recorded zero. Show all activity episodes, sleep intervals and collected workout fields through detailed tables, without implying GPS/trace collection.

## Source integrity

Band data_type=0 consists of 1440 triples (raw category, raw intensity, minute step count). Require exactly4320 decoded bytes and agreement with the supplied daily total. Thirty initial archived days pass that independent check; further live backfill archives were also validated without mismatches. Unknown formats or inconsistent totals leave detail unavailable with an explanation; the daily summary remains usable. Raw category/intensity values have no invented physical units or activity labels.

Sources: [Huami protocol analysis](https://changy-.github.io/articles/xiao-mi-band-protocol-analyze.html), [Gadgetbridge original parser](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huami/operations/fetch/FetchActivityOperation.java). Minute zero is a recorded count, not the heart-rate missing sentinel. Unsigned step byte255 is not discarded. Filter unfinished/future minutes using the archive observation time, so reopening an older current-day buffer cannot manufacture newly elapsed zeroes. Unsupported DST transition buffers remain explicit rather than spilling into the next day.

Preserve known event fields at valid original timestamps. A dayId without a timestamp remains daily data; never synthesize a minute observation. Blood oxygen history without individual timestamps remains archived, not fabricated as measurements.

## Interaction refinements

The user identified the typical-day date slider as awkward and requested a more useful sleep display, plus date-range styling consistent with the dashboard. Preview the draft date while dragging and commit loading on release, suppressing stale responses. Replace crowded sleep segments with overnight stage lanes, totals/timing and exact interval detail; retain gaps. Harmonize the existing Flatpickr calendar with dashboard colors, typography and mobile touch spacing.

## Recovery and export

Read detail from raw archives, so existing dates gain detail without refetching. Add zepp_steps_minute gauge (steps in that minute, not a counter). Migration5 adds/requeues band metric backfill once, using idempotent outbox inserts and original observation cutoff; restart resumes pending exports. Preserve existing metrics. Export retains original legacy summary semantics and enriches newly supported minute detail from raw archives. Fixed 1440-minute step buffers on DST transition days remain unsupported until their clock mapping is verified. Grafana gains4 bounded minute-detail panels; Web UI tables remain exact even when Grafana resamples broad ranges.

## Verification

Test known byte layout, exact times, zero/255, unsupported/truncated/mismatched formats, unfinished-minute cutoff, legacy-archive parsing, repeatable migration/outbox, signed event values and timestamp absence. Browser tests exercise metric switching, zoom, exact timestamp tables and pagination at mobile/desktop widths. Check all dashboard queries in isolated VictoriaMetrics, CI container restart and production archive recovery before marking deployment complete.
