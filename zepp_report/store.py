"""SQLite archive, task checkpoints and transactional metric outbox."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from .migrations import migrate


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as con:
            con.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                  day TEXT, kind TEXT, raw TEXT NOT NULL, data TEXT NOT NULL, updated_at REAL NOT NULL,
                  PRIMARY KEY(day,kind));
                CREATE TABLE IF NOT EXISTS raw_versions (
                  day TEXT, kind TEXT, hash TEXT, raw TEXT NOT NULL, fetched_at REAL NOT NULL,
                  PRIMARY KEY(day,kind,hash));
                CREATE TABLE IF NOT EXISTS samples (
                  id INTEGER PRIMARY KEY, day TEXT, kind TEXT, metric TEXT NOT NULL, timestamp INTEGER NOT NULL,
                  value REAL NOT NULL, sent INTEGER DEFAULT 0, attempted INTEGER DEFAULT 0,
                  conflict INTEGER DEFAULT 0, UNIQUE(metric,timestamp));
                CREATE TABLE IF NOT EXISTS tasks (
                  day TEXT, kind TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                  updated_at REAL NOT NULL, PRIMARY KEY(day,kind));
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            migrate(con)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def meta(self, key, default=None):
        with self.connect() as con:
            row = con.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.connect() as con:
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,dump(value)))

    def archive_raw(self, day, kind, raw):
        serialized = dump(raw)
        with self.connect() as con:
            con.execute('INSERT OR IGNORE INTO raw_versions VALUES (?,?,?,?,?)',
                        (day,kind,hashlib.sha256(serialized.encode()).hexdigest(),serialized,time.time()))

    def telemetry(self, lines):
        with self.connect() as con:
            for line in lines:
                for timestamp,value in zip(line['timestamps'],line['values'],strict=True):
                    con.execute('INSERT OR IGNORE INTO samples(day,kind,metric,timestamp,value) VALUES (?,?,?,?,?)',
                                ('','system',dump(line['metric']),timestamp,value))
            con.execute("DELETE FROM samples WHERE kind='system' AND sent=1 AND timestamp<?",(int((time.time()-86400)*1000),))

    def save(self, day, kind, raw, data, lines):
        now, raw_json = time.time(), dump(raw)
        with self.connect() as con:
            con.execute('INSERT OR IGNORE INTO raw_versions VALUES (?,?,?,?,?)',
                        (day,kind,hashlib.sha256(raw_json.encode()).hexdigest(),raw_json,now))
            con.execute('''INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(day,kind)
                DO UPDATE SET raw=excluded.raw,data=excluded.data,updated_at=excluded.updated_at''',
                (day,kind,raw_json,dump(data),now))
            keys = set()
            for line in lines:
                metric = dump(line['metric'])
                for ts, value in zip(line['timestamps'],line['values'], strict=True):
                    keys.add((metric,ts))
                    old = con.execute('SELECT * FROM samples WHERE metric=? AND timestamp=?',(metric,ts)).fetchone()
                    if old is None:
                        con.execute('INSERT INTO samples(day,kind,metric,timestamp,value) VALUES (?,?,?,?,?)',(day,kind,metric,ts,value))
                    elif old['value'] != value:
                        if old['attempted'] or old['sent']:
                            con.execute('UPDATE samples SET conflict=1 WHERE id=?',(old['id'],))
                        else:
                            con.execute('UPDATE samples SET value=?,conflict=0 WHERE id=?',(value,old['id']))
                    elif old['conflict']:
                        con.execute('UPDATE samples SET conflict=0 WHERE id=?',(old['id'],))
            # Retractions of previously observed samples are also revisions.
            for old in con.execute('SELECT * FROM samples WHERE day=? AND kind=?',(day,kind)).fetchall():
                if json.loads(old['metric'])['__name__'].endswith('_current'):
                    continue
                if (old['metric'],old['timestamp']) not in keys:
                    if old['attempted'] or old['sent']:
                        con.execute('UPDATE samples SET conflict=1 WHERE id=?',(old['id'],))
                    else:
                        con.execute('DELETE FROM samples WHERE id=?',(old['id'],))
            if kind=='workouts':
                con.execute('DELETE FROM metadata WHERE key=?',('workouts:'+day,))
            # Archive, outbox and completion checkpoint must survive as one transaction.
            con.execute("UPDATE tasks SET status='done',error=NULL,updated_at=? WHERE day=? AND kind=?",(now,day,kind))
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('last_success',dump(now)))

    def workout_checkpoint(self,day):
        return self.meta('workouts:'+day)

    def checkpoint_workout_page(self,day,page,checkpoint):
        checkpoint=dict(checkpoint)
        checkpoint['pages']=checkpoint.get('pages',[])+[page]
        checkpoint['cursor']=page['data']['next']
        checkpoint['seen']=checkpoint.get('seen',[])+[page['data']['next']]
        with self.connect() as con:
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('workouts:'+day,dump(checkpoint)))
            con.execute("UPDATE tasks SET status='pending',updated_at=? WHERE day=? AND kind='workouts'",(time.time(),day))

    def pending(self, limit=2000):
        with self.connect() as con:
            return [dict(row) for row in con.execute('SELECT * FROM samples WHERE sent=0 ORDER BY id LIMIT ?',(limit,))]

    def attempted(self, ids):
        with self.connect() as con:
            con.executemany('UPDATE samples SET attempted=1 WHERE id=?',[(i,) for i in ids])

    def ack(self, ids):
        with self.connect() as con:
            con.executemany('UPDATE samples SET sent=1 WHERE id=?',[(i,) for i in ids])

    def raw(self, day, kind):
        with self.connect() as con:
            row = con.execute('SELECT raw FROM records WHERE day=? AND kind=?',(day,kind)).fetchone()
            return json.loads(row[0]) if row else None

    def days(self, start, end):
        with self.connect() as con:
            rows = con.execute('SELECT day,data,updated_at FROM records WHERE day BETWEEN ? AND ? ORDER BY day,kind',(start,end)).fetchall()
        days = {}
        for row in rows:
            day = days.setdefault(row['day'], {'date':row['day'],'summary':{},'heart_rate':[],'stress':[],'sleep_stages':[],'updated_at':0})
            data = json.loads(row['data'])
            day['summary'].update(data.get('summary',{}))
            for key in ('heart_rate','stress','sleep_stages','activity','workout_activity'):
                if data.get(key):
                    day[key] = data[key]
            day['updated_at'] = max(day['updated_at'],row['updated_at'])
        return list(days.values())

    def enqueue(self, days, kinds, include_done=True, reset_workouts=False):
        now, count = time.time(), 0
        with self.connect() as con:
            for day in days:
                for kind in kinds:
                    cur = con.execute('''INSERT INTO tasks(day,kind,updated_at) VALUES (?,?,?)
                      ON CONFLICT(day,kind) DO UPDATE SET status='pending',error=NULL,updated_at=excluded.updated_at
                      WHERE tasks.status='failed' OR (tasks.status='done' AND ?)''',(day,kind,now,int(include_done)))
                    count += cur.rowcount
                    if cur.rowcount and reset_workouts and kind=='workouts':
                        con.execute('DELETE FROM metadata WHERE key=?',('workouts:'+day,))
        return count

    def recover(self):
        with self.connect() as con:
            con.execute("UPDATE tasks SET status='pending' WHERE status='running'")

    def claim(self):
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY day DESC,kind LIMIT 1").fetchone()
            if row:
                con.execute("UPDATE tasks SET status='running',updated_at=? WHERE day=? AND kind=?",(time.time(),row['day'],row['kind']))
                return dict(row)

    def finish(self, task, status='done', error=None):
        with self.connect() as con:
            con.execute('UPDATE tasks SET status=?,error=?,updated_at=? WHERE day=? AND kind=?',
                        (status,error,time.time(),task['day'],task['kind']))

    def retry_failed(self, start=None, end=None, kinds=None):
        conditions, params = ["status='failed'"], []
        if start is not None and end is not None:
            conditions.append('day BETWEEN ? AND ?')
            params.extend([start,end])
        if kinds:
            conditions.append('kind IN ('+','.join('?' for _ in kinds)+')')
            params.extend(kinds)
        with self.connect() as con:
            return con.execute("UPDATE tasks SET status='pending',error=NULL WHERE "+' AND '.join(conditions),params).rowcount

    def resume_auth(self):
        with self.connect() as con:
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('auth_required','false'))
            con.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('next_sync','0'))
            con.execute("UPDATE tasks SET status='pending',error=NULL WHERE status='failed'")

    def stats(self):
        with self.connect() as con:
            tasks = dict.fromkeys(('pending','running','failed','done'),0)
            tasks.update({r['status']:r['n'] for r in con.execute('SELECT status,count(*) AS n FROM tasks GROUP BY status')})
            return {'tasks':tasks,
                    'pending_exports':con.execute('SELECT count(*) FROM samples WHERE sent=0').fetchone()[0],
                    'conflicts':con.execute('SELECT count(*) FROM samples WHERE conflict=1').fetchone()[0],
                    'recent_tasks':[dict(r) for r in con.execute('SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 30')]}

    def has_data(self):
        with self.connect() as con:
            return (con.execute('SELECT 1 FROM records LIMIT 1').fetchone() is not None
                    or con.execute('SELECT 1 FROM raw_versions LIMIT 1').fetchone() is not None
                    or con.execute("SELECT 1 FROM metadata WHERE key LIKE 'workouts:%' LIMIT 1").fetchone() is not None)
