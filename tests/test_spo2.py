import json
from zepp_report.normalize import normalize,day_ms
from zepp_report.store import Store
from zepp_report.analytics_store import AnalyticsStore
from zepp_report.analytics import trends,profile
from zepp_report.metrics import metric_lines
from zepp_report.client import ZeppClient


def test_spo2_events_use_verified_timestamp_not_untimed_history():
    ts=day_ms('2026-09-01','Asia/Shanghai')
    raw={'items':[{'timestamp':ts,'extra':json.dumps({'spo2':97,'spo2History':[98]*60,'isAuto':True})},
                  {'timestamp':ts+60000,'extra':{'spo2':99}},
                  {'timestamp':ts+120000,'extra':{'spo2':True}},
                  {'timestamp':ts+180000,'extra':{'spo2':0}},
                  {'timestamp':ts+240000,'extra':{'spo2':101}},
                  {'timestamp':ts-1,'extra':{'spo2':95}}]}
    result=normalize('spo2','2026-09-01',raw,'Asia/Shanghai')
    assert result['spo2']==[{'time':ts,'value':97},{'time':ts+60000,'value':99}]
    assert result['summary']['spo2_avg']==98
    lines=metric_lines('2026-09-01',result,'personal','Asia/Shanghai')
    assert next(x for x in lines if x['metric']['__name__']=='zepp_spo2_percent')['values']==[97,99]


def test_spo2_daily_index_profile_and_coverage(tmp_path):
    ts=day_ms('2026-09-01','Asia/Shanghai')
    store=Store(tmp_path/'test.db')
    for day,value in [('2026-09-01',96),('2026-09-02',98)]:
        raw={'items':[{'timestamp':day_ms(day,'Asia/Shanghai'),'extra':{'spo2':value}}]}
        store.save(day,'spo2',raw,normalize('spo2',day,raw,'Asia/Shanghai'),[])
    index=AnalyticsStore(store,'Asia/Shanghai');index.rebuild_all()
    data=trends(index,'2026-09-01','2026-09-02')
    assert data['summary']['spo2']['value']==97
    assert data['days'][0]['spo2']['observed_minutes']==1
    assert profile(index,'2026-09-01','2026-09-02','spo2')['buckets'][0]['p50']==97
    assert index.detail('2026-09-01')['spo2'][0]['value']==96


def test_spo2_client_uses_existing_complete_window_fetch():
    seen=[]
    class Client(ZeppClient):
        def request(self,path,params,**kw):
            seen.append((path,params))
            return {'items':[]}
    client=Client({'user_id':'123','timezone':'Asia/Shanghai'})
    assert client.fetch('spo2','2026-09-01')['items']==[]
    path,params=seen[0]
    assert path=='/users/123/events'
    assert params['eventType']=='blood_oxygen' and params['subType']=='click'


def test_upgrade_queues_spo2_and_sleep_backfill_once_across_restart(tmp_path):
    path=tmp_path/'upgrade.db'
    store=Store(path)
    store.enqueue(['2026-09-01'],['band'])
    with store.connect() as con:
        con.execute('DELETE FROM schema_migrations WHERE version=4')
        con.execute("INSERT INTO metric_backfill(day,kind,done) VALUES ('2026-09-01','band',1)")
    store=Store(path)
    with store.connect() as con:
        assert con.execute("SELECT status FROM tasks WHERE kind='spo2'").fetchone()[0]=='pending'
        assert con.execute('SELECT done FROM metric_backfill').fetchone()[0]==0
        con.execute("UPDATE tasks SET status='done' WHERE kind='spo2'")
        con.execute('UPDATE metric_backfill SET done=1')
    store=Store(path)
    with store.connect() as con:
        assert con.execute("SELECT status FROM tasks WHERE kind='spo2'").fetchone()[0]=='done'
        assert con.execute('SELECT done FROM metric_backfill').fetchone()[0]==1
