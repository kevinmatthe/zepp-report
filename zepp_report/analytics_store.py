"""Durable derived indexes. Crashes cannot consume work before its result commits."""
import hashlib
import json
import time
from .activity import band_activity, activity_minutes, band_sleep_bounds
from .analytics import daily_profile, sleep_summary, stats
from .migrations import ALGORITHM_VERSION
from .normalize import normalize, day_bounds
from .store import dump


class AnalyticsStore:
    def __init__(self,store,timezone):
        self.store,self.timezone=store,timezone
        with store.connect() as con:
            con.execute("UPDATE analytics_jobs SET status='pending' WHERE status='running'")
            con.execute('''UPDATE analytics_jobs SET status='pending',retry_at=0 WHERE day IN
                (SELECT j.day FROM analytics_jobs j LEFT JOIN analytics_days d ON j.day=d.day
                 WHERE d.day IS NULL OR d.version!=? OR d.timezone!=?
                 OR coalesce(json_extract(d.data,'$.activity_count'),-1) !=
                    (SELECT count(*) FROM analytics_activities a WHERE a.day=j.day))''',(ALGORITHM_VERSION,timezone))

    def status(self):
        with self.store.connect() as con:
            counts={r['status']:r['n'] for r in con.execute('SELECT status,count(*) n FROM analytics_jobs GROUP BY status')}
        return {'pending':counts.get('pending',0)+counts.get('running',0),
                'failed':counts.get('failed',0),'ready':counts.get('done',0)}

    def _detail(self,day,rows):
        detail={'date':day,'summary':{},'heart_rate':[],'stress':[],'spo2':[],'sleep_stages':[], 'activities':[], 'workouts':[]}
        sleep_bounds=None
        for row in rows:
            data=json.loads(row['data'])
            raw=json.loads(row['raw'])
            detail['summary'].update(data.get('summary',{}))
            for key in ('heart_rate','stress','spo2','sleep_stages'):
                if data.get(key):
                    detail[key]=data[key]
            if row['kind']=='workouts':
                detail['workouts']=data.get('workouts',[])
            if row['kind']=='band':
                # Reparse additional dimensions without changing archives, tasks, or outbox.
                sleep_bounds=band_sleep_bounds(raw,day,self.timezone)
                parsed=normalize('band',day,raw,self.timezone)
                detail['summary'].update(parsed['summary'])
                for key in ('heart_rate','sleep_stages'):
                    if parsed.get(key):
                        detail[key]=parsed[key]
                summary,episodes=band_activity(raw,day,self.timezone)
                detail['summary'].update(summary)
                detail['activities']=episodes
        detail['summary'].update(sleep_summary(detail['sleep_stages'],self.timezone,sleep_bounds))
        detail['activity']=activity_minutes(detail['activities'])
        detail['workout_activity']={}
        for row in detail['workouts']:
            if 'minutes' in row:
                key=row['type']
                detail['workout_activity'][key]=detail['workout_activity'].get(key,0)+row['minutes']
        if 'light_activity' in detail['activity']:
            detail['summary']['light_activity_minutes']=detail['activity']['light_activity']
        low,high=day_bounds(day,self.timezone)
        detail['coverage']={key:{'observed_minutes':len({int(x['time'])//60000 for x in detail[key] if low<=x['time']<high}),
                                  'expected_minutes':(high-low)//60000,'n':len(detail[key])}
                            for key in ('heart_rate','stress','spo2')}
        detail['profiles']={key:daily_profile(detail[key],self.timezone) for key in ('heart_rate','stress','spo2')}
        return detail

    def detail(self,day):
        with self.store.connect() as con:
            rows=con.execute('SELECT * FROM records WHERE day=? ORDER BY kind',(day,)).fetchall()
        return dict(self._detail(day,rows),timezone=self.timezone,algorithm_version=ALGORITHM_VERSION)

    def tick(self):
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            job=con.execute("""SELECT * FROM analytics_jobs WHERE status='pending'
                OR (status='failed' AND retry_at<=?) ORDER BY day DESC LIMIT 1""",(time.time(),)).fetchone()
            if job is None:
                return False
            con.execute("UPDATE analytics_jobs SET status='running' WHERE day=?",(job['day'],))
            rows=con.execute('SELECT * FROM records WHERE day=? ORDER BY kind',(job['day'],)).fetchall()
        try:
            detail=self._detail(job['day'],rows)
            revision=hashlib.sha256(dump([[r['kind'],r['raw'],r['data']] for r in rows]).encode()).hexdigest()
            daily={key:detail[key] for key in ('date','summary','activity','workout_activity')}
            daily['activity_count']=len(detail['activities'])+len(detail['workouts'])
            for key in ('heart_rate','stress','spo2'):
                daily[key]=stats(x['value'] for x in detail[key])
                low,high=day_bounds(job['day'],self.timezone)
                observed=len({int(x['time'])//60000 for x in detail[key] if low<=x['time']<high})
                expected=(high-low)//60000
                daily[key].update(observed_minutes=observed,expected_minutes=expected,
                                  coverage=observed/expected)
            with self.store.connect() as con:
                con.execute('BEGIN IMMEDIATE')
                current=con.execute('SELECT generation FROM analytics_jobs WHERE day=?',(job['day'],)).fetchone()
                if current['generation']!=job['generation']:
                    return True  # New archive version already queued by transactional trigger.
                con.execute('INSERT OR REPLACE INTO analytics_days VALUES (?,?,?,?,?,?)',
                            (job['day'],revision,ALGORITHM_VERSION,self.timezone,dump(daily),dump(detail['profiles'])))
                con.execute('DELETE FROM analytics_activities WHERE day=?',(job['day'],))
                con.executemany('INSERT INTO analytics_activities VALUES (?,?,?,?,?)',
                    [(job['day'],i,row['source'],row['type'],dump(row))
                     for i,row in enumerate(detail['activities']+detail['workouts'])])
                con.execute("UPDATE analytics_jobs SET status='done',error=NULL,retry_at=0 WHERE day=?",(job['day'],))
        except Exception:
            with self.store.connect() as con:
                con.execute("""UPDATE analytics_jobs SET status='failed',error='统计重建失败，稍后自动重试',retry_at=?
                    WHERE day=? AND generation=?""",(time.time()+60,job['day'],job['generation']))
        return True

    def rebuild_all(self):
        while self.tick():
            pass

    def recover(self):
        with self.store.connect() as con:
            con.execute("UPDATE analytics_jobs SET status='pending' WHERE status='running'")

    def rows(self,start,end):
        with self.store.connect() as con:
            rows=con.execute('''SELECT j.day,j.status,d.revision,d.version,d.timezone,d.data,d.profiles
                FROM analytics_jobs j LEFT JOIN analytics_days d ON d.day=j.day
                WHERE j.day BETWEEN ? AND ? ORDER BY j.day''',(start,end)).fetchall()
        return [{'day':r['day'],'revision':r['revision'] or '',
                 'pending':r['status']!='done' or r['version']!=ALGORITHM_VERSION or r['timezone']!=self.timezone,
                 'data':json.loads(r['data']) if r['data'] else {},
                 'profiles':json.loads(r['profiles']) if r['profiles'] else {}} for r in rows]

    def activities(self,start,end,limit=50,offset=0,type=None,source=None):
        where="a.day BETWEEN ? AND ? AND j.status='done' AND d.version=? AND d.timezone=?"
        params=[start,end,ALGORITHM_VERSION,self.timezone]
        for key,value in (('type',type),('source',source)):
            if value is not None:
                where+=' AND a.'+key+'=?';params.append(value)
        join=' FROM analytics_activities a JOIN analytics_jobs j ON a.day=j.day JOIN analytics_days d ON a.day=d.day WHERE '+where
        with self.store.connect() as con:
            total=con.execute('SELECT count(*)'+join,params).fetchone()[0]
            rows=con.execute('SELECT a.day,a.data'+join+' ORDER BY a.day DESC,a.position LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
        return {'activities':[dict(json.loads(r['data']),date=r['day']) for r in rows],
                'total':total,'index':self.status(),'timezone':self.timezone}
