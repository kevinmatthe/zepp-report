import base64
import json
from datetime import date

import pytest

from zepp_report import analytics
from zepp_report.analytics_store import AnalyticsStore
from zepp_report.normalize import day_ms
from zepp_report.store import Store


def band(steps=100, stages=None):
    return {'data': [{'date_time': '2026-09-01', 'summary': base64.b64encode(json.dumps({'stp': {'ttl': steps, 'wk': 12, 'rn': 4, 'stage': stages or []}}).encode()).decode()}]}


def save(store, day, values, steps=100):
    ts=day_ms(day,'Asia/Shanghai')
    store.save(day,'band',{}, {'summary': {'steps':steps}, 'heart_rate':[{'time':ts+i*60000,'value':v} for i,v in enumerate(values)]}, [])


def test_quantiles_interpolate_and_missing_is_not_zero():
    assert analytics.stats([10,20,30,40]) == {'n':4,'mean':25,'p10':13,'p25':17.5,'p50':25,'p75':32.5,'p90':37}
    assert analytics.stats([])['p50'] is None


def test_profile_weights_days_equally_and_requires_sufficient_days(tmp_path):
    store=Store(tmp_path/'test.db')
    save(store,'2026-09-01',[60,60,60,60,60])
    save(store,'2026-09-02',[100])
    index=AnalyticsStore(store,'Asia/Shanghai')
    index.rebuild_all()
    result=analytics.profile(index,'2026-09-01','2026-09-03','heart_rate')
    bucket=result['buckets'][0]
    assert bucket['mean']==80 and bucket['p50']==80 and bucket['n']==2
    assert bucket['p25'] is None
    assert len(result['buckets'])==288
    assert result['buckets'][1]['n']==0


def test_index_crash_resume_and_same_content_and_outbox_untouched(tmp_path):
    store=Store(tmp_path/'test.db')
    save(store,'2026-09-01',[60],0)
    index=AnalyticsStore(store,'Asia/Shanghai')
    assert index.status()['pending']==1
    index.rebuild_all()
    before=index.rows('2026-09-01','2026-09-01')[0]['revision']
    save(store,'2026-09-01',[60],0)
    assert index.status()['pending']==0
    save(store,'2026-09-01',[80],0)
    assert index.status()['pending']==1
    assert analytics.trends(index,'2026-09-01','2026-09-01')['days'][0]['quality']=='index_pending'
    # Simulate process loss after claiming work. Startup recovers in-progress rows.
    with store.connect() as con:
        con.execute("UPDATE analytics_jobs SET status='running'")
    index=AnalyticsStore(Store(store.path),'Asia/Shanghai')
    index.rebuild_all()
    row=index.rows('2026-09-01','2026-09-01')[0]
    assert row['revision']!=before and row['data']['heart_rate']['p50']==80
    assert store.stats()['pending_exports']==0


def test_missing_days_zero_and_comparison(tmp_path):
    store=Store(tmp_path/'test.db')
    save(store,'2026-08-31',[60],0)
    save(store,'2026-09-01',[80],100)
    index=AnalyticsStore(store,'Asia/Shanghai'); index.rebuild_all()
    result=analytics.trends(index,'2026-09-01','2026-09-02',compare='previous')
    assert len(result['days'])==2 and result['days'][1]['summary']=={}
    assert result['summary']['steps']['value']==100
    assert result['summary']['steps']['previous']==0
    assert result['summary']['steps']['percent'] is None
    assert result['summary']['steps']['valid_days']==1
    assert result['comparison']=={'from_date':'2026-08-30','to_date':'2026-08-31'}


def test_year_comparison_clamps_leap_day():
    assert analytics.comparison_range('2024-02-29','2024-03-01','year')==('2023-02-28','2023-03-01')
    assert analytics.comparison_range('2026-03-01','2026-03-31','previous')==('2026-02-01','2026-02-28')


def test_activity_and_sleep_reparse_without_vm_changes(tmp_path):
    store=Store(tmp_path/'test.db')
    raw=band(stages=[{'start':60,'stop':70,'mode':7},{'start':60,'stop':70,'mode':7},{'start':100,'stop':110,'mode':999}])
    store.save('2026-09-01','band',raw,{'summary':{'steps':100}},[])
    index=AnalyticsStore(store,'Asia/Shanghai'); index.rebuild_all()
    detail=index.detail('2026-09-01')
    assert len(detail['activities'])==2
    assert detail['activities'][0]['type']=='running'
    assert detail['activities'][1]['type']=='unknown_999'
    assert detail['summary']['walking_minutes']==12
    assert store.pending()==[]


def test_sleep_overlap_is_never_double_counted():
    result=analytics.sleep_summary([
        {'start':0,'end':3600000,'stage':'light'},
        {'start':1800000,'end':5400000,'stage':'deep'},
        {'start':5400000,'end':6000000,'stage':'awake'},
    ], 'Asia/Shanghai')
    assert result['actual_sleep_minutes']==60
    assert result['sleep_unknown_minutes']==30
    assert result['sleep_awake_minutes']==10
    assert result['sleep_span_minutes']==100


def test_failed_index_retries_and_concurrent_archive_does_not_commit_stale_result(tmp_path,monkeypatch):
    store=Store(tmp_path/'test.db'); save(store,'2026-09-01',[60])
    index=AnalyticsStore(store,'Asia/Shanghai')
    original=index._detail
    def fail(*args): raise OSError('temporary')
    monkeypatch.setattr(index,'_detail',fail)
    assert index.tick() and index.status()['failed']==1
    with store.connect() as con: con.execute('UPDATE analytics_jobs SET retry_at=0')
    def concurrent(day,rows):
        result=original(day,rows)
        save(store,day,[90])
        return result
    monkeypatch.setattr(index,'_detail',concurrent)
    index.tick()
    assert index.status()['pending']==1
    assert index.rows('2026-09-01','2026-09-01')[0]['pending']
    monkeypatch.setattr(index,'_detail',original)
    index.rebuild_all()
    assert index.rows('2026-09-01','2026-09-01')[0]['data']['heart_rate']['p50']==90


def test_dst_repeated_hour_counts_as_one_day():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz=ZoneInfo('America/New_York')
    readings=[{'time':datetime(2026,11,1,1,30,tzinfo=tz,fold=fold).timestamp()*1000,'value':value}
              for fold,value in ((0,60),(1,100))]
    assert analytics.daily_profile(readings,str(tz))==[{'minute':90,'value':80}]


def test_sleep_bounds_include_unobserved_edges_and_clip_stages():
    result=analytics.sleep_summary([{'start':600000,'end':1200000,'stage':'light'},
                                   {'start':1800000,'end':4200000,'stage':'deep'}], 'Asia/Shanghai',bounds=(0,3600000))
    assert result['sleep_span_minutes']==60
    assert result['actual_sleep_minutes']==40
    assert result['sleep_unknown_minutes']==20


def test_negative_balance_no_percent_and_unequal_month_daily_mean(tmp_path):
    store=Store(tmp_path/'test.db')
    for day,steps,tsb in [('2026-02-01',100,-5),('2026-03-01',200,-2)]:
        store.save(day,'training',{}, {'summary':{'steps':steps,'tsb':tsb}},[])
    index=AnalyticsStore(store,'Asia/Shanghai');index.rebuild_all()
    result=analytics.trends(index,'2026-03-01','2026-03-31','previous')
    assert result['summary']['tsb']['delta']==3
    assert result['summary']['tsb']['percent'] is None
    assert result['summary']['steps']['comparison_basis']=='day_mean'
    assert result['summary']['steps']['delta']==100
    assert result['summary']['steps']['comparison_quality']=='insufficient'


def test_deleted_cache_is_rebuilt_and_empty_week_is_not_observed(tmp_path):
    store=Store(tmp_path/'test.db');store.save('2026-09-01','band',{}, {'summary':{}},[])
    index=AnalyticsStore(store,'Asia/Shanghai');index.rebuild_all()
    with store.connect() as con:con.execute('DELETE FROM analytics_days')
    index=AnalyticsStore(store,'Asia/Shanghai')
    assert index.status()['pending']==1
    index.rebuild_all()
    weekly=analytics.trends(index,'2026-09-01','2026-09-02',grain='week')['days'][0]
    assert weekly['valid_days']==0
    assert weekly['metrics']['heart_rate']['valid_days']==0


def test_actual_day_coverage_and_sleep_uncertainty(tmp_path):
    store=Store(tmp_path/'test.db')
    ts=day_ms('2026-03-08','America/New_York')
    store.save('2026-03-08','band',{}, {'summary':{},'heart_rate':[{'time':ts,'value':60}]},[])
    index=AnalyticsStore(store,'America/New_York');index.rebuild_all()
    daily=analytics.trends(index,'2026-03-08','2026-03-08')['days'][0]
    assert daily['heart_rate']['observed_minutes']==1
    assert daily['heart_rate']['expected_minutes']==1380
    profile=analytics.profile(index,'2026-03-08','2026-03-08','heart_rate')
    assert profile['buckets'][24]['eligible_days']==0
    quality=analytics.sleep_summary([{'start':0,'end':600000,'stage':'light'},
                                     {'start':300000,'end':900000,'stage':'deep'}], 'UTC')
    assert quality['sleep_overlap_minutes']==5
    assert quality['sleep_stage_coverage'] == pytest.approx(2/3)


def test_activity_cache_can_be_deleted_and_recovered(tmp_path):
    store=Store(tmp_path/'test.db')
    raw=band(stages=[{'start':60,'stop':70,'mode':7}])
    store.save('2026-09-01','band',raw,{'summary':{}},[])
    index=AnalyticsStore(store,'Asia/Shanghai');index.rebuild_all()
    assert index.activities('2026-09-01','2026-09-01')['total']==1
    with store.connect() as con:con.execute('DROP TABLE analytics_activities')
    index=AnalyticsStore(Store(store.path),'Asia/Shanghai')
    assert index.status()['pending']==1
    index.rebuild_all()
    assert index.activities('2026-09-01','2026-09-01')['total']==1
