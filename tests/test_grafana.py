"""Validate dashboard/schema integration and guard against misleading sparse data."""
import json
from pathlib import Path
import re

from zepp_report.metrics import SUMMARY_KEYS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = 'victoriametrics-metrics-datasource'
OPS = {'zepp_sync_' + key for key in (
    'pending_tasks', 'failed_tasks', 'auth_required', 'pending_exports',
    'conflicts', 'last_success_timestamp_seconds')}


def dashboard():
    return json.loads((ROOT / 'grafana/dashboards/zepp-health.json').read_text())


def targets():
    return [(p, t) for p in dashboard()['panels'] for t in p.get('targets', [])]


def test_metrics_match_exporter_and_cover_all_health_domains():
    used = set()
    allowed = {f'zepp_{key}_{suffix}' for key in SUMMARY_KEYS for suffix in ('daily', 'current')}
    allowed |= OPS | {'zepp_heart_rate_bpm', 'zepp_stress', 'zepp_spo2_percent', 'zepp_steps_minute'}
    allowed |= {f'zepp_{domain}_type_minutes_{suffix}'
                for domain in ('activity', 'workout') for suffix in ('daily', 'current')}
    for _, target in targets():
        names = set(re.findall(r'\bzepp_[a-z0-9_]+\b', target['expr']))
        assert names <= allowed, names - allowed
        assert 'account=~"${account:regex}"' in target['expr']
        assert 'or vector(0)' not in target['expr']
        used |= names
    assert {f'zepp_{key}_daily' for key in SUMMARY_KEYS} <= used
    assert OPS <= used


def test_sparse_daily_and_current_queries_have_bounded_freshness():
    for panel, target in targets():
        expr = target['expr']
        if '_daily{' in expr:
            assert 'last_over_time(' in expr and '[1d]' in expr
            assert 'tlast_over_time(' in expr
            assert 'floor((time() + 28800) / 86400) * 86400 - 28800' in expr
            assert target['interval'] == '1d'
            assert target['utcOffsetSec'] == 28800
            assert panel['fieldConfig']['defaults']['custom']['spanNulls'] is False
        if '_current{' in expr:
            assert target['instant'] is True and target['range'] is False
            assert 'tlast_over_time(' in expr
            assert 'floor((now() + 28800) / 86400) * 86400 - 28800' in expr
            assert '@ now()' in expr
            assert 'lastNotNull' not in panel['options']['reduceOptions']['calcs']
        if 'zepp_sync_' in expr:
            assert '[3m]' in expr  # offline exporter becomes unknown, not forever healthy


def test_provisioning_and_import_use_native_datasource():
    data = dashboard()
    variables = {v['name']: v for v in data['templating']['list']}
    assert variables['DS_VICTORIAMETRICS']['type'] == 'datasource'
    assert variables['DS_VICTORIAMETRICS']['query'] == PLUGIN
    assert variables['DS_VICTORIAMETRICS']['current']['value'] == 'zepp-victoriametrics'
    assert variables['account']['current']['value'] == 'personal'
    for panel, target in targets():
        for obj in (panel, target):
            assert obj['datasource'] == {'type': PLUGIN, 'uid': '${DS_VICTORIAMETRICS}'}
    provisioning = (ROOT / 'grafana/provisioning/datasources/zepp.yaml').read_text()
    assert f'type: {PLUGIN}' in provisioning
    assert 'uid: zepp-victoriametrics' in provisioning
    assert 'url: ${VM_QUERY_URL}' in provisioning
    provider = (ROOT / 'grafana/provisioning/dashboards/zepp.yaml').read_text()
    assert 'path: /etc/dashboards/zepp-report' in provider


def test_panels_have_unique_ids_and_nonoverlapping_layout():
    data = dashboard()
    assert data['timezone'] == 'Asia/Shanghai'
    ids, occupied = set(), set()
    for panel in data['panels']:
        assert panel['id'] not in ids
        ids.add(panel['id'])
        g = panel['gridPos']
        assert 0 <= g['x'] < 24 and g['w'] > 0 and g['x'] + g['w'] <= 24
        cells = {(x, y) for x in range(g['x'], g['x'] + g['w']) for y in range(g['y'], g['y'] + g['h'])}
        assert occupied.isdisjoint(cells)
        occupied |= cells


def test_overview_prioritizes_activity_sleep_and_exercise():
    data = dashboard()
    assert data['uid'] == 'zepp-health'
    hero = [p for p in data['panels'] if p['type'] == 'stat' and p['gridPos']['y'] < 10]
    expressions = ' '.join(t['expr'] for p in hero for t in p['targets'])
    for key in ('steps', 'actual_sleep_minutes', 'resting_hr', 'stress_avg', 'workout_minutes', 'workout_count'):
        assert f'zepp_{key}_current' in expressions
    assert all(p['gridPos']['h'] >= 5 for p in hero)
    trend_panels = [p for p in data['panels'] if p['type'] == 'timeseries']
    assert 'zepp_steps_daily' in trend_panels[0]['targets'][0]['expr']
    assert 'zepp_actual_sleep_minutes_daily' in trend_panels[1]['targets'][0]['expr']


def test_percentiles_are_explicit_rolling_windows_without_gap_filling():
    percentile_panels = [p for p in dashboard()['panels'] if '分位' in p['title']]
    assert len(percentile_panels) == 2
    for panel in percentile_panels:
        assert '24' in panel['title'] and '滚动' in panel['description']
        expressions = ' '.join(t['expr'] for t in panel['targets'])
        for quantile in ('0.1', '0.5', '0.9'):
            assert f'quantile_over_time({quantile},' in expressions
        assert '[24h]' in expressions
        assert panel['fieldConfig']['defaults']['custom']['spanNulls'] is False


def test_typed_duration_series_preserve_type_labels_and_freshness():
    for domain in ('workout', 'activity'):
        found = [t for _, t in targets() if f'zepp_{domain}_type_minutes_daily' in t['expr']]
        assert len(found) == 1
        assert '{{type}}' in found[0]['legendFormat']
        assert 'tlast_over_time(' in found[0]['expr']


def test_spo2_has_fresh_today_average_and_daily_and_observed_trends():
    selected = [(p, t) for p, t in targets() if 'zepp_spo2_' in t['expr']]
    assert len({p['id'] for p, _ in selected}) == 4
    expressions = ' '.join(t['expr'] for _, t in selected)
    for name in ('zepp_spo2_avg_current', 'zepp_spo2_avg_daily', 'zepp_spo2_percent'):
        assert name in expressions
    for panel, target in selected:
        defaults = panel['fieldConfig']['defaults']
        assert defaults['unit'] == 'percent'
        assert defaults['min'] == 0 and defaults['max'] == 100
        assert 'thresholds' not in defaults
        if '_current' in target['expr']:
            assert panel['gridPos']['y'] < 13 and panel['type'] == 'stat'
        if 'zepp_spo2_percent{' in target['expr']:
            assert ('[$__interval]' if panel['title'].endswith('· 分钟明细') else '[5m]') in target['expr']
            assert panel['fieldConfig']['defaults']['custom']['spanNulls'] is False


def test_fine_detail_panels_adapt_resolution_and_preserve_aggregate_semantics():
    panels = [p for p in dashboard()['panels'] if p['title'].endswith('· 分钟明细')]
    assert len(panels) == 4
    for panel in panels:
        assert panel['interval'] == '1m'
        # Plugin interval rounding may return up to ~2x the requested budget.
        assert 1000 <= panel['maxDataPoints'] <= 5000
        for target in panel['targets']:
            expr = target['expr']
            assert target['interval'] == '1m'
            assert '[$__interval]' in expr
            assert 'tlast_over_time(' in expr and '> time() - $__interval_ms / 1000' in expr
            assert 'rate(' not in expr and 'or vector(0)' not in expr
        if panel['title'].startswith('步数'):
            assert len(panel['targets']) == 1
            assert 'sum_over_time(zepp_steps_minute' in panel['targets'][0]['expr']
        else:
            assert len(panel['targets']) == 3
            for rollup in ('avg_over_time','min_over_time','max_over_time'):
                assert any(target['expr'].startswith(rollup+'(') for target in panel['targets'])
        custom = panel['fieldConfig']['defaults']['custom']
        assert custom['spanNulls'] is False and custom['lineWidth'] == 0
        assert 'WebUI' in panel['description'] and '降采样' in panel['description']


def test_dashboard_point_budgets_leave_room_below_vm_30000_limit():
    for panel in dashboard()['panels']:
        if panel['type']=='timeseries':
            assert 0<panel.get('maxDataPoints',1000)<=10000
