"""Normalize the formats documented by EvanCooke/zepp-export (see notices)."""
import base64
import json
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KINDS = ('band', 'stress', 'training', 'trimp', 'sport', 'vo2', 'workouts')
STAGES = {4: 'light', 5: 'deep', 7: 'awake', 8: 'rem'}


def day_ms(day, timezone):
    return int(datetime.combine(date.fromisoformat(day), time(), ZoneInfo(timezone)).timestamp() * 1000)


def day_bounds(day, timezone):
    return day_ms(day, timezone), day_ms((date.fromisoformat(day) + timedelta(days=1)).isoformat(), timezone)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def copy_numbers(source, mapping, target):
    for key, name in mapping.items():
        n = number(source.get(key))
        if n is not None:
            target[name] = n


def normalize(kind, day, raw, timezone):
    if kind == 'workouts':
        from .workouts import normalize_workouts
        return normalize_workouts(raw, day, timezone)
    low, high = day_bounds(day, timezone)
    result = {'summary': {}, 'heart_rate': [], 'stress': [], 'sleep_stages': []}
    summary = result['summary']
    if kind == 'band':
        candidates = []
        for row in raw.get('data', []):
            source_day = row.get('date_time')
            if not source_day:
                raise ValueError('Band data missing date')
            encoded = row.get('summary')
            decoded = json.loads(base64.b64decode(encoded, validate=True)) if encoded else {}
            if not isinstance(decoded, dict):
                raise ValueError('Invalid summary')
            base = day_ms(source_day, timezone)
            if source_day == day:
                copy_numbers(decoded.get('stp', {}), {'ttl':'steps','dis':'distance_meters','cal':'calories'}, summary)
                hr = base64.b64decode(row.get('data_hr') or '', validate=True)
                if len(hr) > 1440:
                    raise ValueError('Unexpected heart rate length')
                result['heart_rate'] = [{'time': base + i*60000, 'value': bpm}
                                        for i, bpm in enumerate(hr) if 0 < bpm < 254]
            slp = decoded.get('slp', {})
            start, end = number(slp.get('st')), number(slp.get('ed'))
            if start and end and start < end and low <= end*1000 < high:
                candidates.append((end-start, base, slp))
        if candidates:
            _, base, slp = max(candidates, key=lambda row: row[0])
            summary['sleep_minutes'] = (float(slp['ed']) - float(slp['st'])) / 60
            copy_numbers(slp, {'ss':'sleep_score','rhr':'resting_hr'}, summary)
            # Zero score/resting HR represent missing measurements in Zepp sleep summaries.
            for key in ('sleep_score', 'resting_hr'):
                if summary.get(key) == 0:
                    summary.pop(key)
            for stage in slp.get('stage') or slp.get('odd_stage') or []:
                a, b = number(stage.get('start')), number(stage.get('stop'))
                if a is None or b is None or b <= a:
                    continue
                name = STAGES.get(stage.get('mode'), 'unknown')
                result['sleep_stages'].append({'start': int(base+a*60000), 'end': int(base+b*60000), 'stage': name})
                key = f'sleep_{name}_minutes'
                summary[key] = summary.get(key, 0) + b-a
    else:
        items = raw.get('items', [])
        if not isinstance(items, list):
            raise ValueError('Invalid event items')
        # Latest daily result wins, independently of server ordering.
        items = sorted(items, key=lambda x: number(x.get('timestamp')) or 0)
        for row in items:
            ts = number(row.get('timestamp'))
            if kind in ('sport', 'vo2'):
                source_day = str(row.get('dayId', ''))
                if source_day and source_day != day:
                    continue
                if not source_day and (ts is None or not low <= ts < high):
                    continue
            elif ts is None or not low <= ts < high:
                continue
            if kind == 'stress':
                copy_numbers(row, {'avgStress':'stress_avg'}, summary)
                readings = row.get('data', [])
                if isinstance(readings, str):
                    readings = json.loads(readings) if readings else []
                for sample in readings:
                    t, v = number(sample.get('time')), number(sample.get('value'))
                    if t is not None and v is not None and low <= t < high and 0 < v <= 100:
                        result['stress'].append({'time': int(t), 'value': v})
            elif kind == 'training':
                copy_numbers(row.get('value', {}), {'atl':'atl','ctl':'ctl','tsb':'tsb'}, summary)
            elif kind == 'trimp':
                copy_numbers(row.get('value', {}).get('result', {}), {'trimp':'trimp'}, summary)
            elif kind == 'sport':
                copy_numbers(row, {'currnetDayTrainLoad':'sport_load', 'wtlSum':'weekly_load',
                                  'wtlSumOptimalMin':'sport_optimal_min', 'wtlSumOptimalMax':'sport_optimal_max'}, summary)
            elif kind == 'vo2':
                # Upstream has no confirmed populated fixture. Preserve unknown schemas raw.
                copy_numbers(row, {'vo2Max':'vo2_max'}, summary)
    if kind == 'band':
        from .activity import band_activity, activity_minutes, band_sleep_bounds
        from .analytics import sleep_summary
        extra,episodes=band_activity(raw,day,timezone)
        summary.update(extra)
        result['activities']=episodes
        result['activity']=activity_minutes(episodes)
        sleep=sleep_summary(result['sleep_stages'],timezone,band_sleep_bounds(raw,day,timezone))
        # Keep existing VM sleep duration definitions stable; add identifiable sleep only.
        if 'actual_sleep_minutes' in sleep:
            summary['actual_sleep_minutes']=sleep['actual_sleep_minutes']
    for field in ('heart_rate', 'stress'):
        result[field] = [{'time': k, 'value': v} for k, v in sorted({x['time']: x['value'] for x in result[field]}.items())]
    return result
