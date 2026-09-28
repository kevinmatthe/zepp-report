"""Known band activity episodes; these are not complete workout recordings."""
import base64
import json
from .normalize import day_ms, day_bounds, number

MODES = {1: 'slow_walking', 3: 'fast_walking', 7: 'running', 76: 'light_activity'}


def band_activity(raw, day, timezone):
    summary, episodes = {}, {}
    for row in raw.get('data', []):
        if row.get('date_time') != day:
            continue
        decoded = json.loads(base64.b64decode(row.get('summary') or 'e30=', validate=True))
        steps = decoded.get('stp', {})
        for key, target in {'wk':'walking_minutes','rn':'running_minutes','runDist':'running_distance_meters',
                            'runCal':'running_calories'}.items():
            value = number(steps.get(key))
            if value is not None and value >= 0:
                summary[target] = value
        base = day_ms(day, timezone)
        for stage in steps.get('stage') or []:
            start, end = number(stage.get('start')), number(stage.get('stop'))
            if start is None or end is None or not 0 <= start < end <= 1440:
                continue
            mode = stage.get('mode')
            if not isinstance(mode, (int, str)) or isinstance(mode, bool):
                mode = 'unknown'
            kind = MODES.get(mode, 'unknown_' + str(mode))
            a, b = int(base + start*60000), int(base + end*60000)
            episode = {'start':a, 'end':b, 'minutes':end-start, 'type':kind,
                       'mode':mode, 'source':'band_episode'}
            for key,target in {'step':'steps','dis':'distance_meters','cal':'calories'}.items():
                value=number(stage.get(key))
                if value is not None and value>=0:
                    episode[target]=value
            episodes[(a,b,str(mode))]=episode
    return summary, sorted(episodes.values(), key=lambda x:(x['start'],x['end'],str(x['mode'])))


def activity_minutes(episodes):
    # Union within each type, retain unknown codes. Types may overlap and are explicitly episodes.
    groups = {}
    for row in episodes:
        groups.setdefault(row['type'], []).append((row['start'],row['end']))
    result = {}
    for kind, spans in groups.items():
        total, end = 0, float('-inf')
        for a,b in sorted(spans):
            total += max(0,b-max(a,end))
            end=max(end,b)
        result[kind]=total/60000
    return result


def band_sleep_bounds(raw,day,timezone):
    low,high=day_bounds(day,timezone)
    candidates=[]
    for row in raw.get('data',[]):
        decoded=json.loads(base64.b64decode(row.get('summary') or 'e30=',validate=True))
        slp=decoded.get('slp',{})
        start,end=number(slp.get('st')),number(slp.get('ed'))
        if start and end and start<end and low<=end*1000<high:
            candidates.append((start*1000,end*1000))
    return max(candidates,key=lambda x:x[1]-x[0]) if candidates else None
