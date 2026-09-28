import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from zepp_report.normalize import day_ms
from zepp_report.store import Store, dump


class Response:
    status_code = 200

    def __init__(self, rows=(), payload=None):
        self.payload = payload if payload is not None else '\n'.join(json.dumps(row) for row in rows).encode()

    def iter_content(self, chunk_size=65536):
        yield self.payload

    def close(self):
        pass


class Transport:
    def __init__(self, response=None, callback=None):
        self.response = response if response is not None else Response()
        self.callback = callback
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.callback:
            self.callback()
        return self.response


def setup_archive(tmp_path, age=1, values=(60,), offsets=None):
    store = Store(tmp_path/'audit.db')
    settings = SimpleNamespace(vm_query_url='http://vm/select/0/prometheus', vm_token='private-token',
                               vm_retention_days=None, vm_dedup_seconds=0, account='personal',
                               snapshot=lambda: {'interval_minutes': 30, 'timezone': 'UTC'})
    day = (datetime.now(timezone.utc).date()-timedelta(days=age)).isoformat()
    base = day_ms(day, 'UTC')
    metric = {'__name__': 'zepp_heart_rate_bpm', 'account': 'personal'}
    timestamps = [base+offset for offset in (offsets or [i*60000 for i in range(len(values))])]
    with store.connect() as con:
        con.executemany('INSERT INTO samples(day,kind,metric,timestamp,value,sent,attempted) VALUES (?,?,?,?,?,1,1)',
                        [(day, 'band', dump(metric), ts, value) for ts, value in zip(timestamps, values)])
    return store, settings, day, {'metric': metric, 'timestamps': timestamps, 'values': list(values)}


def auditor(store, settings, transport=None):
    from zepp_report.vm_audit import VMAuditor
    result = VMAuditor(settings, store, transport or Transport())
    result.schedule(force=True)
    with store.connect() as con:
        con.execute('UPDATE vm_audits SET next_check=0')
    return result


def job(store, day):
    with store.connect() as con:
        return dict(con.execute('SELECT * FROM vm_audits WHERE day=?', (day,)).fetchone())


def due(store):
    with store.connect() as con:
        con.execute('UPDATE vm_audits SET next_check=0')


def test_silent_drop_repairs_then_restart_requires_remote_verification(tmp_path):
    store, settings, day, row = setup_archive(tmp_path, values=(60, 70))
    transport = Transport(Response([dict(row, timestamps=row['timestamps'][:1], values=[60])]))
    worker = auditor(store, settings, transport)
    assert worker.tick()
    assert job(store, day)['state'] == 'waiting'
    assert job(store, day)['missing'] == 1
    assert len(store.pending()) == 1 and store.pending()[0]['value'] == 70
    assert store.pending()[0]['attempted'] == 1
    assert worker.tick() is False
    # A successful replay acknowledgement alone must not certify persistence.
    store.ack([store.pending()[0]['id']])
    from zepp_report.vm_audit import VMAuditor
    worker = VMAuditor(settings, Store(store.path), Transport(Response([row])))
    worker.recover()
    due(store)
    assert worker.tick()
    assert job(store, day)['state'] == 'verified'
    assert job(store, day)['repaired'] == 1
    assert worker.status()['configured'] is True
    assert worker.status()['missing_samples'] == 0


def test_retention_expiry_never_repairs_or_queries(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path, age=10)
    settings.vm_retention_days = 2
    transport = Transport()
    worker = auditor(store, settings, transport)
    worker.tick()
    assert job(store, day)['state'] == 'expired'
    assert not store.pending() and not transport.calls
    worker.schedule(force=True)
    worker.tick()
    assert not store.pending() and not transport.calls


def test_same_timestamp_mismatch_is_conflict_without_overwrite(tmp_path):
    store, settings, day, row = setup_archive(tmp_path)
    worker = auditor(store, settings, Transport(Response([dict(row, values=[90])])))
    worker.tick()
    assert job(store, day)['state'] == 'conflict'
    assert job(store, day)['conflicts'] == 1
    assert not store.pending()


def test_dedup_15_seconds_checks_only_latest_point_in_bucket(tmp_path):
    store, settings, day, row = setup_archive(tmp_path, values=(60, 70, 80), offsets=[1000, 14000, 16000])
    settings.vm_dedup_seconds = 15
    remote = dict(row, timestamps=row['timestamps'][1:], values=row['values'][1:])
    worker = auditor(store, settings, Transport(Response([remote])))
    worker.tick()
    assert job(store, day)['state'] == 'verified'
    assert job(store, day)['total'] == 2
    assert not store.pending()


def test_generation_change_discards_stale_network_missing_result(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path)
    def concurrent_archive():
        with store.connect() as con:
            con.execute('UPDATE vm_audits SET generation=generation+1 WHERE day=?', (day,))
    worker = auditor(store, settings, Transport(callback=concurrent_archive))
    worker.tick()
    assert job(store, day)['state'] == 'pending'
    assert not store.pending()


@pytest.mark.parametrize('payload', [b'not-json', b'{"status":"error","message":"secret"}',
                                    b'{"metric":{},"values":[1],"timestamps":[]}'])
def test_bad_export_fails_safely_and_retries_without_reset(tmp_path, payload):
    store, settings, day, _ = setup_archive(tmp_path)
    worker = auditor(store, settings, Transport(Response(payload=payload)))
    worker.tick()
    state = job(store, day)
    assert state['state'] == 'failed' and state['next_check'] > time.time()
    assert not store.pending()
    assert 'secret' not in (state['error'] or '')


def test_schedule_preserves_pending_work_and_recovers_running_claim(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path)
    worker = auditor(store, settings)
    with store.connect() as con:
        con.execute("UPDATE vm_audits SET state='running',generation=7")
    worker.schedule(force=True)
    assert job(store, day)['state'] == 'running'
    worker.recover()
    assert job(store, day)['state'] == 'pending'
    assert job(store, day)['generation'] == 7


def test_pending_delivery_defers_audit_without_network_call(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path)
    with store.connect() as con:
        con.execute('UPDATE samples SET sent=0')
    transport = Transport()
    worker = auditor(store, settings, transport)
    worker.tick()
    assert job(store, day)['state'] == 'waiting'
    assert not transport.calls


@pytest.mark.parametrize('seconds,offsets,kept', [
    (15, [0, 1, 15000, 15001], [0, 2, 3]),
    (.001, [0, 1, 2], [0, 1, 2]),
])
def test_vm_right_inclusive_bucket_boundary_and_one_millisecond_precision(tmp_path, seconds, offsets, kept):
    store, settings, day, row = setup_archive(tmp_path, values=tuple(range(len(offsets))), offsets=offsets)
    settings.vm_dedup_seconds = seconds
    remote = dict(row, timestamps=[row['timestamps'][i] for i in kept], values=[row['values'][i] for i in kept])
    worker = auditor(store, settings, Transport(Response([remote])))
    worker.tick()
    assert job(store, day)['state'] == 'verified'
    assert job(store, day)['total'] == len(kept)


def test_partial_retention_skips_expired_points_and_repairs_only_retained(tmp_path):
    store, settings, day, row = setup_archive(tmp_path, values=(60, 70), offsets=[0, 80000000])
    worker = auditor(store, settings)
    worker._cutoff = lambda: row['timestamps'][0] + 1000
    worker.tick()
    assert job(store, day)['missing'] == 1
    assert [r['value'] for r in store.pending()] == [70]


def test_http_failure_is_sanitized_and_does_not_repair(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path)
    response = Response(payload=b'secret token detail')
    response.status_code = 503
    worker = auditor(store, settings, Transport(response))
    worker.tick()
    assert job(store, day)['state'] == 'failed'
    assert not store.pending()
    assert 'secret' not in worker.status()['error']


def test_network_failure_is_sanitized_and_retried(tmp_path):
    import requests
    store, settings, day, _ = setup_archive(tmp_path)
    def unavailable():
        raise requests.ConnectionError('private-token')
    worker = auditor(store, settings, Transport(callback=unavailable))
    worker.tick()
    assert job(store, day)['state'] == 'failed'
    assert not store.pending()
    assert 'private-token' not in worker.status()['error']


def test_local_revision_conflict_never_replays_older_dedup_point(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path, values=(60, 70), offsets=[1000, 14000])
    settings.vm_dedup_seconds = 15
    with store.connect() as con:
        con.execute('UPDATE samples SET conflict=1 WHERE value=70')
    worker = auditor(store, settings)
    worker.tick()
    assert job(store, day)['state'] == 'conflict'
    assert job(store, day)['conflicts'] == 1
    assert not store.pending()


def test_request_is_account_scoped_and_authenticated(tmp_path):
    store, settings, _, row = setup_archive(tmp_path)
    transport = Transport(Response([row]))
    worker = auditor(store, settings, transport)
    worker.tick()
    url, kwargs = transport.calls[0]
    assert url == settings.vm_query_url + '/api/v1/export'
    assert kwargs['params']['match[]'] == '{__name__=~"zepp_.*",account="personal"}'
    assert kwargs['headers'] == {'Authorization': 'Bearer private-token'}
    assert kwargs['allow_redirects'] is False
    assert kwargs['stream'] is True


def test_disabled_query_configuration_never_schedules_or_sends(tmp_path):
    store, settings, _, _ = setup_archive(tmp_path)
    settings.vm_query_url = ''
    worker = auditor(store, settings)
    assert worker.schedule(force=True) == 0
    assert worker.tick() is False
    assert worker.status()['configured'] is False


def test_schedule_honors_interval_and_excludes_telemetry(tmp_path):
    store, settings, day, _ = setup_archive(tmp_path)
    worker = auditor(store, settings)
    with store.connect() as con:
        con.execute("UPDATE vm_audits SET state='verified'")
        con.execute("INSERT INTO samples(day,kind,metric,timestamp,value) VALUES ('','system','{}',1,1)")
    assert worker.schedule() == 0
    assert job(store, day)['state'] == 'verified'
    assert worker.schedule(force=True) == 1
    assert job(store, day)['state'] == 'pending'
    with store.connect() as con:
        assert con.execute('SELECT count(*) FROM vm_audits').fetchone()[0] == 1
