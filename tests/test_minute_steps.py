import base64,json
from zepp_report.normalize import normalize,day_ms
from zepp_report.store import Store
from zepp_report.analytics_store import AnalyticsStore
from zepp_report.metrics import metric_lines,backfill_additional_metrics


def raw_steps(values,**changes):
    minutes=values+[0]*(1440-len(values))
    row={'date_time':'2026-09-01','data_type':0,
         'data':base64.b64encode(bytes(b for value in minutes for b in (1,2,value))).decode(),
         'summary':base64.b64encode(json.dumps({'stp':{'ttl':sum(minutes)}}).encode()).decode()}
    row.update(changes)
    return {'data':[row]}


def test_minute_steps_exact_clock_and_recorded_zero():
    result=normalize('band','2026-09-01',raw_steps([0,12,255]),'Asia/Shanghai')
    ts=day_ms('2026-09-01','Asia/Shanghai')
    assert len(result['steps'])==1440
    assert result['steps'][:3]==[{'time':ts+i*60000,'value':v} for i,v in enumerate([0,12,255])]
    line=next(x for x in metric_lines('2026-09-01',result,'personal','Asia/Shanghai') if x['metric']['__name__']=='zepp_steps_minute')
    assert line['values'][:3]==[0,12,255]


def test_unsupported_or_inconsistent_steps_do_not_fail_other_data():
    for changes in ({'data_type':7},{'data':base64.b64encode(bytes(9)).decode()},
                    {'summary':base64.b64encode(b'{"stp":{"ttl":999}}').decode()}):
        result=normalize('band','2026-09-01',raw_steps([12],**changes),'Asia/Shanghai')
        assert result['steps']==[]
        assert result['steps_quality']['status'] in ('unsupported','inconsistent')


def test_archived_minute_steps_reparse_and_export_recoverably(tmp_path):
    store=Store(tmp_path/'archive.db');raw=raw_steps([0,10,20])
    store.save('2026-09-01','band',raw,{'summary':{'steps':30}},[])
    detail=AnalyticsStore(store,'Asia/Shanghai').detail('2026-09-01')
    assert detail['steps'][1]['value']==10
    assert detail['coverage']['steps']['observed_minutes']==1440
    with store.connect() as con:
        con.execute('DELETE FROM schema_migrations WHERE version=5')
    store=Store(store.path)
    assert backfill_additional_metrics(store,'personal','Asia/Shanghai')
    with store.connect() as con:
        count=con.execute("SELECT count(*) FROM samples WHERE json_extract(metric,'$.__name__')='zepp_steps_minute'").fetchone()[0]
    assert count==1440
    store=Store(store.path)
    assert not backfill_additional_metrics(store,'personal','Asia/Shanghai')
    assert len(store.pending(2000))==1440


def test_current_buffer_excludes_unfinished_and_future_minutes():
    ts=day_ms('2026-09-01','Asia/Shanghai')
    result=normalize('band','2026-09-01',raw_steps([0,12,9]),'Asia/Shanghai',observed_until=ts+125000)
    assert result['steps']==[{'time':ts,'value':0},{'time':ts+60000,'value':12}]


def test_fixed_1440_buffer_does_not_spill_across_dst_days():
    for day in ('2026-03-08','2026-11-01'):
        raw=raw_steps([12]);raw['data'][0]['date_time']=day
        result=normalize('band',day,raw,'America/New_York')
        assert result['steps']==[]
        assert result['steps_quality']['status']=='unsupported'
