"""Transparent day-weighted descriptive statistics; no clinical interpretations."""
import calendar
import hashlib
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from .normalize import number, day_bounds
from .migrations import ALGORITHM_VERSION


def days_between(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a+timedelta(days=i)).isoformat() for i in range((b-a).days+1)]


def stats(values):
    values = sorted(v for x in values if (v := number(x)) is not None)
    n=len(values)
    result={'n':n, 'mean':sum(values)/n if n else None}
    for p in (10,25,50,75,90):
        h=(n-1)*p/100
        lo,hi=math.floor(h),math.ceil(h)
        result['p'+str(p)]=values[lo]+(values[hi]-values[lo])*(h-lo) if n else None
    return result


def daily_profile(samples, timezone):
    bins={}
    for sample in samples:
        value=number(sample.get('value'))
        ts=number(sample.get('time'))
        if value is None or ts is None:
            continue
        local=datetime.fromtimestamp(ts/1000,ZoneInfo(timezone))
        minute=(local.hour*60+local.minute)//5*5
        bins.setdefault(minute,[]).append(value)
    # Repeated DST clock bins yield exactly one representative for that day.
    return [{'minute':minute,'value':stats(values)['p50']} for minute,values in sorted(bins.items())]


def sleep_summary(stages, timezone, bounds=None):
    spans=[]
    for s in stages:
        a,b=number(s.get('start')),number(s.get('end'))
        if a is not None and b is not None:
            if bounds:
                a,b=max(a,bounds[0]),min(b,bounds[1])
            if b>a:
                spans.append((a,b,s.get('stage','unknown')))
    if not spans and not bounds:
        return {}
    edges=sorted({p for a,b,_ in spans for p in (a,b)} | (set(bounds) if bounds else set()))
    totals={k:0 for k in ('light','deep','rem','awake','unknown')}
    overlaps=gaps=0
    for a,b in zip(edges,edges[1:]):
        active={kind for start,end,kind in spans if start<b and end>a}
        if len(active)>1: overlaps+=(b-a)/60000
        if not active: gaps+=(b-a)/60000
        kind=next(iter(active)) if len(active)==1 else 'unknown'
        totals[kind if kind in totals else 'unknown']+=(b-a)/60000
    result={'sleep_'+k+'_minutes':v for k,v in totals.items()}
    if spans:
        result['actual_sleep_minutes']=sum(totals[k] for k in ('light','deep','rem'))
    result['sleep_span_minutes']=(edges[-1]-edges[0])/60000
    result['sleep_overlap_minutes']=overlaps
    result['sleep_gap_minutes']=gaps
    result['sleep_stage_coverage']=1-totals['unknown']/result['sleep_span_minutes']
    result['sleep_start']=edges[0]
    result['sleep_end']=edges[-1]
    for key,ts in (('sleep_onset_minutes',edges[0]),('sleep_wake_minutes',edges[-1])):
        t=datetime.fromtimestamp(ts/1000,ZoneInfo(timezone))
        minute=t.hour*60+t.minute
        result[key]=minute if minute>=720 else minute+1440
    return result


def comparison_range(start,end,mode):
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if mode=='year':
        def previous_year(d):
            return d.replace(year=d.year-1,day=min(d.day,calendar.monthrange(d.year-1,d.month)[1]))
        return previous_year(a).isoformat(),previous_year(b).isoformat()
    if mode!='previous':
        return None
    if a.month==1 and a.day==1 and b.month==12 and b.day==31 and a.year==b.year:
        return f'{a.year-1}-01-01',f'{a.year-1}-12-31'
    if a.day==1 and a.year==b.year and a.month==b.month and b.day==calendar.monthrange(b.year,b.month)[1]:
        last=a-timedelta(days=1)
        return last.replace(day=1).isoformat(),last.isoformat()
    length=(b-a).days+1
    return (a-timedelta(days=length)).isoformat(),(a-timedelta(days=1)).isoformat()


def metadata(index,rows):
    revision=hashlib.sha256('|'.join(row['revision'] for row in rows).encode()).hexdigest()[:16]
    return {'timezone':index.timezone,'algorithm_version':ALGORITHM_VERSION,'source_revision':revision,'index':index.status()}


def profile(index,start,end,metric):
    rows=index.rows(start,end)
    bins={}
    for row in rows:
        if row['pending']:
            continue
        for sample in row['profiles'].get(metric,[]):
            bins.setdefault(sample['minute'],[]).append(sample['value'])
    eligible={minute:0 for minute in range(0,1440,5)}
    for day in days_between(start,end):
        low,high=day_bounds(day,index.timezone)
        available=set(range(0,1440,5))
        if high-low!=86400000:
            available={((d:=datetime.fromtimestamp(ts/1000,ZoneInfo(index.timezone))).hour*60+d.minute)//5*5
                       for ts in range(low,high,60000)}
        for minute in available:
            eligible[minute]+=1
    buckets=[]
    for minute in range(0,1440,5):
        stat=stats(bins.get(minute,[]))
        if stat['n']<5:
            for key in ('p10','p25','p75','p90'):
                stat[key]=None
        if stat['n']<2:
            stat['mean']=stat['p50']=None
        buckets.append(dict(stat,minute=minute,eligible_days=eligible[minute]))
    return dict(metadata(index,rows),buckets=buckets,metric=metric,from_date=start,to_date=end,
                grain='5_minutes',quality='index_pending' if any(r['pending'] for r in rows) else 'observed',
                weighting='one_median_per_day_per_clock_bin',minimum_band_days=5,minimum_line_days=2)


UNITS={'steps':'步','distance_meters':'米','calories':'kcal','actual_sleep_minutes':'分钟',
       'sleep_span_minutes':'分钟','sleep_minutes':'分钟','sleep_score':'分','resting_hr':'bpm',
       'workout_minutes':'分钟','workout_count':'次','spo2':'%','spo2_avg':'%','heart_rate':'bpm','stress':'分','walking_minutes':'分钟','running_minutes':'分钟',
       'running_distance_meters':'米','light_activity_minutes':'分钟',
       'sleep_onset_minutes':'分钟','sleep_wake_minutes':'分钟','atl':'负荷','ctl':'负荷','tsb':'负荷','trimp':'负荷','sport_load':'负荷'}
TOTALS={'workout_minutes','workout_count','steps','distance_meters','calories','walking_minutes','running_minutes','running_distance_meters','light_activity_minutes'}


def summarize(days):
    output={}
    keys=set(UNITS)|{k for d in days for k in d['summary']}
    for key in keys:
        values=[]
        for day in days:
            value=day.get(key,{}).get('p50') if key in ('heart_rate','stress','spo2') else day['summary'].get(key)
            if number(value) is not None:
                values.append(value)
        n=len(values); total=len(days)
        mean=sum(values)/n if n else None
        value=sum(values) if n and key in TOTALS else mean
        output[key]={'value':value,'day_mean':mean,'unit':UNITS.get(key,'分钟' if key.endswith('_minutes') else ''),
                     'valid_days':n,'total_days':total,'aggregation':'sum' if key in TOTALS else 'day_mean',
                     'quality':'empty' if not n else ('partial' if n<total else 'complete')}
    return output


def day_rows(index,start,end):
    rows=index.rows(start,end)
    by_day={row['day']:row for row in rows}
    days=[]
    for day in days_between(start,end):
        row=by_day.get(day)
        if row and not row['pending']:
            value=dict(row['data']); value['quality']='observed' if value['summary'] or value['heart_rate']['n'] or value['stress']['n'] or value['spo2']['n'] else 'empty'
        else:
            value={'date':day,'summary':{},'heart_rate':stats([]),'stress':stats([]),'spo2':stats([]),'activity':{},'workout_activity':{},
                   'quality':'index_pending' if row else 'missing'}
        days.append(value)
    return days,rows


def group_days(days,grain):
    if grain=='day':
        return days
    grouped={}
    for day in days:
        d=date.fromisoformat(day['date'])
        key=(d-timedelta(days=d.weekday())).isoformat() if grain=='week' else d.replace(day=1).isoformat()
        grouped.setdefault(key,[]).append(day)
    result=[]
    for key,items in grouped.items():
        sums=summarize(items)
        activity={};workout_activity={}
        for d in items:
            for kind,value in d.get('workout_activity',{}).items():
                workout_activity[kind]=workout_activity.get(kind,0)+value
            for kind,value in d['activity'].items():
                activity[kind]=activity.get(kind,0)+value
        result.append({'date':key,'from_date':items[0]['date'],'to_date':items[-1]['date'],
                       'summary':{k:v['value'] for k,v in sums.items() if k not in ('heart_rate','stress','spo2') and v['value'] is not None},
                       'heart_rate':stats(d['heart_rate']['p50'] for d in items),
                       'stress':stats(d['stress']['p50'] for d in items),'spo2':stats(d['spo2']['p50'] for d in items), 'activity':activity,'workout_activity':workout_activity,
                       'valid_days':sum(d['quality']=='observed' for d in items),'total_days':len(items),'metrics':sums,
                       'quality':'partial' if any(d['quality']!='observed' for d in items) else 'observed',
                       'distribution':'daily_medians'})
    return result


def trends(index,start,end,compare='none',grain='day'):
    days,rows=day_rows(index,start,end)
    today=datetime.now(ZoneInfo(index.timezone)).date().isoformat()
    comparable=[d for d in days if d['date']<today]
    summary=summarize(comparable)
    comparison=None
    # Current incomplete day is shown in plots, excluded from period comparisons.
    window=comparison_range(start,comparable[-1]['date'],compare) if comparable else None
    if window and window[0]>='1970-01-01':
        a,b=window; comparison={'from_date':a,'to_date':b}
        previous,previous_rows=day_rows(index,a,b)
        rows+=previous_rows
        baseline=summarize(previous)
        for key,current in summary.items():
            old=baseline.get(key,{'value':None,'day_mean':None,'valid_days':0,'total_days':len(previous)})
            # For differing period lengths compare totals through daily means.
            use_mean=current['total_days']!=old['total_days'] and key in TOTALS
            x=current['day_mean'] if use_mean else current['value']
            y=old['day_mean'] if use_mean else old['value']
            delta=x-y if x is not None and y is not None else None
            low=any(v['valid_days'] < min(7,v['total_days']) or v['valid_days']/max(v['total_days'],1)<.7 for v in (current,old))
            current.update(previous=old['value'],previous_day_mean=old['day_mean'],delta=delta,
                           percent=(delta/y*100 if delta is not None and y>0 and key not in ('tsb','sleep_onset_minutes','sleep_wake_minutes') else None),
                           previous_valid_days=old['valid_days'],previous_total_days=old['total_days'],
                           comparison_basis='day_mean' if use_mean else current['aggregation'],
                           comparison_quality='insufficient' if low else 'complete')
    for value in summary.values():
        for key in ('previous','delta','percent'):
            value.setdefault(key,None)
    # Rolling average counts observed days, never inserts missing zeros.
    for i,day in enumerate(days):
        values=[d['summary']['steps'] for d in days[max(0,i-6):i+1] if 'steps' in d['summary']]
        day['steps_rolling_mean']=sum(values)/len(values) if values else None
        day['steps_rolling_days']=len(values)
    return dict(metadata(index,rows),days=group_days(days,grain),summary=summary,comparison=comparison,
                from_date=start,to_date=end,grain=grain,today=today,
                summary_range={'from_date':comparable[0]['date'],'to_date':comparable[-1]['date']} if comparable else None,
                summary_excludes_today=end>=today,comparison_excludes_today=True,quality='index_pending' if any(r['pending'] for r in rows) else 'observed')
