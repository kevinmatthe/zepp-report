"""Stable metric schema; never represent absent observations as zero."""
from collections import defaultdict
from datetime import datetime
import json
from zoneinfo import ZoneInfo
from .normalize import day_ms

SUMMARY_KEYS = ('steps','distance_meters','calories','sleep_score','sleep_minutes','resting_hr',
                'sleep_deep_minutes','sleep_light_minutes','sleep_rem_minutes','sleep_awake_minutes',
                'stress_avg','atl','ctl','tsb','trimp','sport_load','weekly_load','sport_optimal_min','sport_optimal_max','vo2_max')


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
