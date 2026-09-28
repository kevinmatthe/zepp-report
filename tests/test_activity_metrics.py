import base64,json
from zepp_report.normalize import normalize
from zepp_report.metrics import metric_lines
from zepp_report.store import Store
from zepp_report.analytics_store import AnalyticsStore


def raw_band():
    return {'data':[{'date_time':'2026-09-01','summary':base64.b64encode(json.dumps({'stp':{'ttl':100,'wk':10,'rn':5,'runDist':500,'stage':[{'start':60,'stop':65,'mode':7}]}}).encode()).decode()}]}


def test_activity_daily_metric_names_types_and_units():
    data=normalize('band','2026-09-01',raw_band(),'Asia/Shanghai')
    rows=metric_lines('2026-09-01',data,'personal','Asia/Shanghai')
    by_name={r['metric']['__name__']:r for r in rows}
    assert by_name['zepp_running_distance_meters_daily']['values']==[500]
    assert by_name['zepp_walking_minutes_daily']['values']==[10]
    typed=by_name['zepp_activity_type_minutes_daily']
    assert typed['metric']['type']=='running' and typed['values']==[5]


def test_new_metrics_backfill_is_additive_durable_and_idempotent(tmp_path):
    from zepp_report.metrics import backfill_additional_metrics
    store=Store(tmp_path/'test.db')
    original={'metric':{'__name__':'zepp_steps_daily','account':'personal'},'timestamps':[1],'values':[100]}
    store.save('2026-09-01','band',raw_band(),{'summary':{'steps':100}},[original])
    store.attempted([store.pending()[0]['id']]);store.ack([store.pending()[0]['id']])
    with store.connect() as con:con.execute("INSERT INTO metric_backfill(day,kind) VALUES('2026-09-01','band')")
    assert backfill_additional_metrics(store,'personal','Asia/Shanghai')
    pending=store.pending();assert pending
    assert all(r['kind']=='band' for r in pending)
    assert not any(json.loads(r['metric'])['__name__']=='zepp_steps_daily' for r in pending)
    assert store.stats()['conflicts']==0
    assert not backfill_additional_metrics(Store(store.path),'personal','Asia/Shanghai')
    assert len(store.pending())==len(pending)


def test_malformed_newest_archive_does_not_starve_older_metric_backfill(tmp_path):
    from zepp_report.metrics import backfill_additional_metrics
    store=Store(tmp_path/'test.db')
    malformed={'data':[{'date_time':'2026-09-02','summary':base64.b64encode(json.dumps({'stp':{'stage':[None]}}).encode()).decode()}]}
    store.save('2026-09-02','band',malformed,{'summary':{}},[])
    store.save('2026-09-01','band',raw_band(),{'summary':{'steps':100}},[])
    with store.connect() as con:
        con.executemany('INSERT INTO metric_backfill(day,kind) VALUES (?,?)',[('2026-09-02','band'),('2026-09-01','band')])
    assert backfill_additional_metrics(store,'personal','Asia/Shanghai')
    assert backfill_additional_metrics(store,'personal','Asia/Shanghai')
    with store.connect() as con:
        assert con.execute("SELECT retry_at FROM metric_backfill WHERE day='2026-09-02'").fetchone()[0]>0
        assert con.execute("SELECT done FROM metric_backfill WHERE day='2026-09-01'").fetchone()[0]==1


def test_export_keeps_typed_activity_series(tmp_path):
    store=Store(tmp_path/'test.db');data=normalize('band','2026-09-01',raw_band(),'Asia/Shanghai')
    store.save('2026-09-01','band',raw_band(),data,[])
    lines=metric_lines('2026-09-01',store.days('2026-09-01','2026-09-01')[0],'personal','Asia/Shanghai',archive=True)
    assert any(x['metric']['__name__']=='zepp_activity_type_minutes_daily' for x in lines)
