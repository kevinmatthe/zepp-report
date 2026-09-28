"""Workout summaries, independent from automatically detected band episodes.

Type mapping evidence: DhavalBhimani44/zepp-mcp codes.py at 9ba4f58.
Unknown codes remain labelled; no inferred mapping for sport_mode.
"""
from .normalize import day_bounds, number

TYPES={1:'outdoor_running',8:'walking',9:'outdoor_cycling',14:'pool_swimming',
       18:'football',21:'rope_skipping',22:'hiking',52:'strength_training'}


def normalize_workouts(raw,day,timezone):
    low,high=day_bounds(day,timezone)
    data=raw.get('data')
    if not isinstance(data,dict) or not isinstance(data.get('summary'),list):
        raise ValueError('Invalid workout summary')
    workouts={}
    for row in data['summary']:
        if not isinstance(row,dict): raise ValueError('Invalid workout row')
        start,end=number(row.get('trackid')),number(row.get('end_time'))
        if start is None or end is None or not 0<start<=end<1e11:
            raise ValueError('Invalid workout timestamps')
        if not low<=start*1000<high:
            continue
        code=row.get('type')
        if not isinstance(code,int) or isinstance(code,bool):
            raise ValueError('Invalid workout type')
        source=row.get('source','')
        if not isinstance(source,str): raise ValueError('Invalid workout source')
        item={'id':str(row['trackid']),'upstream_source':source,'source':'workout','type_code':code,
              'type':TYPES.get(code,'unknown_'+str(code)),'start':int(start*1000),'end':int(end*1000)}
        active=number(row.get('exerciseTimeWithMillis'))
        seconds=active/1000 if active is not None and active>0 else number(row.get('run_time'))
        if seconds is not None and seconds>=0:
            item['minutes']=seconds/60
        for key,target in {'dis':'distance_meters','calorie':'calories','avg_heart_rate':'average_heart_rate'}.items():
            value=number(row.get(key))
            if value is not None and value>=0:
                item[target]=value
        workouts[(item['id'],source)]=item
    items=sorted(workouts.values(),key=lambda x:x['start'])
    # An empty successful workout list is no observation, not zero activity.
    summary={}
    if items:
        summary['workout_count']=len(items)
        durations=[x['minutes'] for x in items if 'minutes' in x]
        if durations: summary['workout_minutes']=sum(durations)
    typed={}
    for item in items:
        if 'minutes' in item: typed[item['type']]=typed.get(item['type'],0)+item['minutes']
    return {'summary':summary,'workout_activity':typed,'workouts':items,'heart_rate':[],'stress':[],'sleep_stages':[]}
