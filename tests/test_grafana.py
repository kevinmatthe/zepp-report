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
    allowed |= OPS | {'zepp_heart_rate_bpm', 'zepp_stress'}
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
    assert 'url: http://vmselect:8481/select/0/prometheus' in provisioning
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
