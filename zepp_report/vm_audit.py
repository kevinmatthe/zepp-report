"""Verify persisted VM samples and replay only proven missing local samples.

Export is deliberately queried without reduce_mem_usage: VM applies its configured
deduplication to that endpoint. Buckets below match lib/storage/dedup.go's
right-inclusive intervals, including samples exactly on an interval boundary.
"""
import json
import math
import time

import requests

from .normalize import day_bounds
from .store import dump


STATES = ('pending', 'running', 'waiting', 'verified', 'conflict', 'expired', 'failed')
MAX_EXPORT_BYTES = 32 * 1024 * 1024
QUERY_ERROR = 'VictoriaMetrics 持久化核对失败，稍后重试；未重置已发送数据'


def _bucket(timestamp, interval):
    return (timestamp + interval - 1) // interval if interval else timestamp


class VMAuditor:
    def __init__(self, settings, store, transport=None):
        self.settings = settings
        self.store = store
        self.transport = transport if transport is not None else requests.Session()

    def _cutoff(self):
        days = self.settings.vm_retention_days
        return time.time() * 1000 - days * 86400000 if days is not None else float('-inf')

    def recover(self):
        with self.store.connect() as con:
            con.execute("UPDATE vm_audits SET state='pending',next_check=0 WHERE state='running'")

    def schedule(self, force=False):
        if not self.settings.vm_query_url:
            return 0
        now = time.time()
        cfg = self.settings.snapshot()
        cutoff = self._cutoff()
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("SELECT value FROM metadata WHERE key='next_vm_audit'").fetchone()
            if not force and row and json.loads(row['value']) > now:
                return 0
            days = con.execute("SELECT DISTINCT day FROM samples WHERE day!='' AND kind!='system'").fetchall()
            queued = 0
            for item in days:
                day = item['day']
                current = con.execute('SELECT state FROM vm_audits WHERE day=?', (day,)).fetchone()
                if current and current['state'] == 'running':
                    continue
                if day_bounds(day, cfg['timezone'])[1] <= cutoff:
                    con.execute('''INSERT INTO vm_audits(day,state) VALUES (?,'expired')
                        ON CONFLICT(day) DO UPDATE SET state='expired',missing=0,conflicts=0,error=NULL''', (day,))
                    continue
                if current and current['state'] in ('pending', 'waiting', 'failed'):
                    continue
                con.execute('''INSERT INTO vm_audits(day,next_check) VALUES (?,?)
                    ON CONFLICT(day) DO UPDATE SET state='pending',generation=generation+1,
                        next_check=excluded.next_check,error=NULL''', (day, now))
                queued += 1
            con.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                        ('next_vm_audit', dump(now + cfg['interval_minutes'] * 60)))
        return queued

    def status(self):
        with self.store.connect() as con:
            counts = dict.fromkeys(STATES, 0)
            counts.update({r['state']: r['n'] for r in con.execute('SELECT state,count(*) n FROM vm_audits GROUP BY state')})
            totals = con.execute('''SELECT max(last_checked) last_checked,
                coalesce(sum(missing),0) missing_samples,coalesce(sum(conflicts),0) conflict_samples,
                coalesce(sum(repaired),0) repaired_samples FROM vm_audits''').fetchone()
            failed = con.execute("SELECT 1 FROM vm_audits WHERE state='failed' LIMIT 1").fetchone()
        return dict(totals, configured=bool(self.settings.vm_query_url),
                    retention_days=self.settings.vm_retention_days,
                    interval_minutes=self.settings.snapshot()['interval_minutes'], states=counts,
                    error=QUERY_ERROR if failed else None)

    def _export(self, start, end, expected):
        headers = {}
        if self.settings.vm_token:
            headers['Authorization'] = 'Bearer ' + self.settings.vm_token
        selector = '{__name__=~"zepp_.*",account=' + json.dumps(self.settings.account) + '}'
        response = self.transport.get(self.settings.vm_query_url.rstrip('/') + '/api/v1/export',
            params={'match[]': selector, 'start': start / 1000, 'end': end / 1000, 'nocache': '1'},
            headers=headers, timeout=(10, 30), allow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                raise ValueError('Export did not succeed')
            payload = bytearray()
            deadline = time.monotonic() + 45
            for chunk in response.iter_content(chunk_size=65536):
                if time.monotonic() > deadline or len(payload) + len(chunk) > MAX_EXPORT_BYTES:
                    raise ValueError('Export exceeds bound')
                payload.extend(chunk)
            remote = {}
            interval = int(round(self.settings.vm_dedup_seconds * 1000))
            for line in payload.decode('utf-8').splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('Invalid export record')
                metric, timestamps, values = row.get('metric'), row.get('timestamps'), row.get('values')
                if (not isinstance(metric, dict) or not isinstance(metric.get('__name__'), str)
                    or not all(isinstance(k, str) and isinstance(v, str) for k, v in metric.items())
                    or not isinstance(timestamps, list) or not isinstance(values, list)
                    or len(timestamps) != len(values)):
                    raise ValueError('Invalid export series')
                series = dump(metric)
                for timestamp, value in zip(timestamps, values, strict=True):
                    if (type(timestamp) is not int or type(value) not in (int, float)
                        or not math.isfinite(value)):
                        raise ValueError('Invalid export sample')
                    key = (series, _bucket(timestamp, interval))
                    if key not in expected:
                        continue
                    old = remote.get(key)
                    if old is None or timestamp > old[0]:
                        remote[key] = (timestamp, {value})
                    elif timestamp == old[0]:
                        old[1].add(value)
            return remote
        finally:
            response.close()

    def tick(self):
        if not self.settings.vm_query_url:
            return False
        now = time.time()
        cfg = self.settings.snapshot()
        cutoff = self._cutoff()
        interval = int(round(self.settings.vm_dedup_seconds * 1000))
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            job = con.execute('''SELECT * FROM vm_audits
                WHERE state IN ('pending','waiting','failed') AND next_check<=?
                ORDER BY next_check,day DESC LIMIT 1''', (now,)).fetchone()
            if job is None:
                return False
            rows = con.execute("SELECT * FROM samples WHERE day=? AND kind!='system'", (job['day'],)).fetchall()
            eligible = [row for row in rows if row['timestamp'] >= cutoff]
            if rows and not eligible:
                con.execute("UPDATE vm_audits SET state='expired',missing=0,conflicts=0,total=0,error=NULL WHERE day=?", (job['day'],))
                return True
            if any(not row['sent'] and not row['conflict'] for row in eligible):
                con.execute("UPDATE vm_audits SET state='waiting',next_check=? WHERE day=?", (now + 15, job['day']))
                return True
            con.execute("UPDATE vm_audits SET state='running',error=NULL WHERE day=?", (job['day'],))
        try:
            expected = {}
            local_conflicts = sum(bool(row['conflict']) for row in eligible)
            for row in eligible:
                metric = json.loads(row['metric'])
                if metric.get('account') != self.settings.account or not metric.get('__name__', '').startswith('zepp_'):
                    continue
                key = (dump(metric), _bucket(row['timestamp'], interval))
                if key not in expected or row['timestamp'] > expected[key]['timestamp']:
                    expected[key] = row
            # Include conflict rows while finding bucket winners, then exclude them:
            # an older point discarded by VM must not be repaired in their place.
            expected = {key: row for key, row in expected.items() if not row['conflict']}
            start, end = day_bounds(job['day'], cfg['timezone'])
            if expected:
                start = min(start, min(row['timestamp'] for row in expected.values()))
                end = max(end, max(row['timestamp'] for row in expected.values()) + 1)
                if interval:
                    start = (_bucket(start, interval) - 1) * interval + 1
                    end = _bucket(end, interval) * interval
                remote = self._export(start, end, expected)
            else:
                remote = {}
            missing, conflicts = [], local_conflicts
            for key, row in expected.items():
                found = remote.get(key)
                if found is None or found[0] < row['timestamp']:
                    missing.append(row)
                elif found[0] == row['timestamp'] and found[1] != {row['value']}:
                    conflicts += 1
                # A later point in the same dedup bucket legitimately replaces ours.
            with self.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                current = con.execute('SELECT generation FROM vm_audits WHERE day=?', (job['day'],)).fetchone()
                if current['generation'] != job['generation']:
                    con.execute("UPDATE vm_audits SET state='pending',next_check=? WHERE day=?", (time.time() + 15, job['day']))
                    return True
                # Retention can advance while the export is in flight.
                missing = [row for row in missing if row['timestamp'] >= self._cutoff()]
                repaired = 0
                for row in missing:
                    repaired += con.execute('''UPDATE samples SET sent=0
                        WHERE id=? AND sent=1 AND conflict=0 AND value=? AND timestamp=? AND metric=?''',
                        (row['id'], row['value'], row['timestamp'], row['metric'])).rowcount
                state = 'waiting' if missing else ('conflict' if conflicts else 'verified')
                delay = 15 if missing else cfg['interval_minutes'] * 60
                con.execute('''UPDATE vm_audits SET state=?,next_check=?,last_checked=?,error=NULL,
                    missing=?,conflicts=?,repaired=repaired+?,total=? WHERE day=?''',
                    (state, time.time() + delay, time.time(), len(missing), conflicts, repaired,
                     len(expected) + local_conflicts, job['day']))
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            with self.store.connect() as con:
                con.execute('''UPDATE vm_audits SET state='failed',next_check=?,error=?
                    WHERE day=? AND generation=?''', (time.time() + 60, QUERY_ERROR, job['day'], job['generation']))
                # A concurrent writer owns the newer generation; do not overwrite it.
                con.execute("""UPDATE vm_audits SET state='pending',next_check=?
                    WHERE day=? AND generation!=? AND state='running'""", (time.time() + 15, job['day'], job['generation']))
        return True
