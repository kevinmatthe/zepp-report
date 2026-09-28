"""Acquisition, observed measurements and delivery are distinct coverage axes."""
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from .analytics import days_between
from .normalize import KINDS

STATES=('done','pending','running','failed','unrequested')


def coverage(store,start,end,timezone,kind=None,today=None,include_tasks=True):
    today=today or datetime.now(ZoneInfo(timezone)).date().isoformat()
    kinds=(kind,) if kind else KINDS
    with store.connect() as con:
        tasks={(r['day'],r['kind']):dict(r) for r in con.execute('SELECT * FROM tasks WHERE day BETWEEN ? AND ?',(start,end))}
        # json_each examines only normalized fields; no raw archives or minute traces in response.
        records={(r['day'],r['kind']):bool(r['observed']) for r in con.execute('''SELECT day,kind,
            (EXISTS(SELECT 1 FROM json_each(json_extract(data,'$.summary')))
             OR coalesce(json_array_length(data,'$.heart_rate'),0)>0
             OR coalesce(json_array_length(data,'$.stress'),0)>0
             OR coalesce(json_array_length(data,'$.sleep_stages'),0)>0) observed
             FROM records WHERE day BETWEEN ? AND ?''',(start,end))}
        delivery={r['day']:dict(r) for r in con.execute('''SELECT day,sum(sent=0) pending_exports,sum(conflict) conflicts
            FROM samples WHERE day BETWEEN ? AND ? GROUP BY day''',(start,end))}
    days=[]; totals=Counter({s:0 for s in STATES})
    for day in days_between(start,end):
        counts=Counter({s:0 for s in STATES}); items=[]
        for k in kinds:
            task=tasks.get((day,k),{})
            archived=(day,k) in records
            status=task.get('status','done' if archived else 'unrequested')
            counts[status]+=1
            items.append({'kind':k,'status':status,'archived':archived,'has_data':records.get((day,k),False),
                          'error':task.get('error')})
        if day>today: state='future'
        elif counts['running']: state='running'
        elif counts['failed']: state='failed'
        elif counts['done']==len(kinds): state='done'
        elif counts['done']: state='partial'
        elif counts['pending']: state='pending'
        else: state='unrequested'
        archived=sum(x['archived'] for x in items); observed=sum(x['has_data'] for x in items)
        row={'date':day,'status':state,'counts':dict(counts),'expected':len(kinds) if day<=today else 0,
             'archived':archived,'observed':observed,'empty':archived-observed,
             'pending_exports':delivery.get(day,{}).get('pending_exports',0),'conflicts':delivery.get(day,{}).get('conflicts',0)}
        if include_tasks: row['tasks']=items
        days.append(row)
        if day<=today:
            totals.update(counts)
    return {'days':days,'totals':dict(totals),'timezone':timezone,'today':today,
            'auth_required':store.meta('auth_required',False)}


def preview(store,start,end,kinds=None,force=False):
    kinds=kinds or KINDS
    with store.connect() as con:
        tasks={(r['day'],r['kind']):r['status'] for r in con.execute('SELECT day,kind,status FROM tasks WHERE day BETWEEN ? AND ?',(start,end))}
    counts=Counter({s:0 for s in STATES})
    for day in days_between(start,end):
        for kind in kinds:
            counts[tasks.get((day,kind),'unrequested')]+=1
    return dict(counts,total=sum(counts.values()),queued=counts['unrequested']+counts['failed']+(counts['done'] if force else 0))
