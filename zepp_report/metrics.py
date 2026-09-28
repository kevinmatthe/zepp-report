"""Stable metric schema; never represent absent observations as zero."""
from collections import defaultdict
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo
from .normalize import day_ms

ADDITIONAL_SUMMARY_KEYS = ('walking_minutes','running_minutes','running_distance_meters','actual_sleep_minutes','workout_count','workout_minutes')
TYPE_METRICS = {'activity':'zepp_activity_type_minutes','workout_activity':'zepp_workout_type_minutes'}

SUMMARY_KEYS = ('steps','distance_meters','calories','sleep_score','sleep_minutes','resting_hr',
                'sleep_deep_minutes','sleep_light_minutes','sleep_rem_minutes','sleep_awake_minutes',
                'stress_avg','atl','ctl','tsb','trimp','sport_load','weekly_load','sport_optimal_min','sport_optimal_max','vo2_max') + ADDITIONAL_SUMMARY_KEYS


def metric_lines(day, data, account, timezone, now=None, archive=False):
    now=now or datetime.now(ZoneInfo(timezone))
    current=day == now.astimezone(ZoneInfo(timezone)).date().isoformat() and not archive
    ts=int(now.timestamp()*1000) if current else day_ms(day,timezone)
    lines=[]
    def add(name,points,**labels):
        if points:
            lines.append({'metric':{'__name__':name,'account':account,**labels},
                          'values':[p[1] for p in points],'timestamps':[int(p[0]) for p in points]})
    for key in SUMMARY_KEYS:
        value=data.get('summary',{}).get(key)
        if value is not None:
            add(f'zepp_{key}_{"current" if current else "daily"}',[(ts,value)])
    for field,name in TYPE_METRICS.items():
        for kind,minutes in data.get(field,{}).items():
            add(f'{name}_{"current" if current else "daily"}',[(ts,minutes)],type=kind)
    add('zepp_heart_rate_bpm',[(p['time'],p['value']) for p in data.get('heart_rate',[])])
    add('zepp_stress',[(p['time'],p['value']) for p in data.get('stress',[])])
    # Exact stage intervals remain in SQLite/UI; Grafana uses stage durations.
    return lines


def sample_lines(rows):
    groups=defaultdict(list)
    for row in rows:
        groups[row['metric']].append((row['timestamp'],row['value']))
    return [{'metric':json.loads(key),'timestamps':[p[0] for p in points], 'values':[p[1] for p in points]}
            for key,points in groups.items()]


def json_lines(lines):
    return ''.join(json.dumps(line,separators=(',',':'),allow_nan=False)+'\n' for line in lines)


def backfill_additional_metrics(store,account,timezone):
    """One durable additive export. Never rewrite/resent old metrics or consume tasks."""
    from .normalize import normalize
    from .store import dump
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        job=con.execute('SELECT * FROM metric_backfill WHERE done=0 AND retry_at<=? ORDER BY day DESC LIMIT 1',(time.time(),)).fetchone()
        if job is None:
            return False
        try:
            record=con.execute('SELECT raw FROM records WHERE day=? AND kind=?',(job['day'],job['kind'])).fetchone()
            data=normalize(job['kind'],job['day'],json.loads(record['raw']),timezone)
            allowed={f'zepp_{k}_{s}' for k in ADDITIONAL_SUMMARY_KEYS for s in ('daily','current')}
            allowed.update(name+'_'+s for name in TYPE_METRICS.values() for s in ('daily','current'))
            for line in metric_lines(job['day'],data,account,timezone):
                if line['metric']['__name__'] not in allowed:
                    continue
                for ts,value in zip(line['timestamps'],line['values'],strict=True):
                    con.execute('INSERT OR IGNORE INTO samples(day,kind,metric,timestamp,value) VALUES (?,?,?,?,?)',
                                (job['day'],job['kind'],dump(line['metric']),ts,value))
            con.execute('UPDATE metric_backfill SET done=1,error=NULL WHERE day=? AND kind=?',(job['day'],job['kind']))
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError,IndexError):
            con.execute("UPDATE metric_backfill SET retry_at=?,error='新增指标解析失败，稍后重试' WHERE day=? AND kind=?",(time.time()+300,job['day'],job['kind']))
    return True
