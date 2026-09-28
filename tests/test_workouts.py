import pytest
from zepp_report.normalize import normalize,day_ms
from zepp_report.store import Store
from zepp_report.settings import Settings
from zepp_report.sync import SyncService
from zepp_report.client import ZeppClient,UpstreamError


def page(next=-1):
    ts=day_ms('2026-09-01','Asia/Shanghai')//1000
    return {'code':1,'data':{'next':next,'summary':[{'trackid':str(ts),'source':'fixture','type':9,
                'end_time':str(ts+600),'run_time':'600','dis':'2000','exerciseTimeWithMillis':600000}]}}


def test_workout_units_type_unknown_dedupe_and_day_filter():
    raw=page();raw['data']['summary']*=2
    data=normalize('workouts','2026-09-01',raw,'Asia/Shanghai')
    assert len(data['workouts'])==1
    assert data['workouts'][0]['minutes']==10
    assert data['workouts'][0]['distance_meters']==2000
    assert data['workouts'][0]['type']=='outdoor_cycling'
    assert normalize('workouts','2026-09-02',raw,'Asia/Shanghai')['workouts']==[]
    raw['data']['summary'][0]['type']=999
    assert normalize('workouts','2026-09-01',raw,'Asia/Shanghai')['workouts'][0]['type']=='unknown_999'


def test_workout_pagination_checkpoint_survives_restart(tmp_path):
    settings=Settings(tmp_path,{'ADMIN_PASSWORD':'test-password-long','ZEPP_USER_ID':'123','ZEPP_TOKEN':'fixture'})
    store=Store(tmp_path/'zepp.sqlite3');store.enqueue(['2026-09-01'],['workouts'])
    cursors=[]
    class Client:
        def __init__(self,cfg):pass
        def fetch_workout_page(self,day,cursor=None):
            cursors.append(cursor)
            return page(123) if cursor is None else {'code':1,'data':{'next':-1,'summary':[]}}
    service=SyncService(settings,store,client_factory=Client)
    assert service.tick()
    assert store.stats()['tasks']['done']==0
    service=SyncService(settings,Store(store.path),client_factory=Client)
    service.store.recover()
    assert service.tick()
    assert cursors==[None,123]
    assert store.stats()['tasks']['done']==1
    assert len(store.days('2026-09-01','2026-09-01'))==1
    assert store.workout_checkpoint('2026-09-01') is None
    assert store.raw('2026-09-01','workouts')['_pages'][0]['data']['next']==123


def test_workout_repeating_cursor_fails_without_consuming_progress(tmp_path):
    settings=Settings(tmp_path,{'ADMIN_PASSWORD':'test-password-long','ZEPP_USER_ID':'123','ZEPP_TOKEN':'fixture'})
    store=Store(tmp_path/'zepp.sqlite3');store.enqueue(['2026-09-01'],['workouts'])
    class Client:
        def __init__(self,cfg):pass
        def fetch_workout_page(self,day,cursor=None):return page(123)
    service=SyncService(settings,store,client_factory=Client)
    service.tick();service.tick()
    assert store.stats()['tasks']['failed']==1
    assert store.workout_checkpoint('2026-09-01')['cursor']==123
    assert store.raw('2026-09-01','workouts') is None


def test_workout_client_preserves_opaque_cursor_and_rejects_partial_shape():
    class Response:
        status_code=200
        def json(self):return page()
    class Transport:
        def get(self,url,**kw):
            assert kw['params']['trackid']==123
            assert kw['params']['from']=='2026-08-31' and kw['params']['to']=='2026-09-02'
            return Response()
    client=ZeppClient({'region':'global','token':'fixture','user_id':'123','timezone':'Asia/Shanghai'},Transport())
    assert client.fetch_workout_page('2026-09-01',123)['data']['next']==-1
    Response.json=lambda self:{'code':1,'data':{'summary':[]}}
    with pytest.raises(UpstreamError):client.fetch_workout_page('2026-09-01',123)


def test_workout_index_keeps_sources_separate_and_filters(tmp_path):
    from zepp_report.analytics_store import AnalyticsStore
    from zepp_report.analytics import trends
    store=Store(tmp_path/'test.db');raw=page()
    store.save('2026-09-01','workouts',raw,normalize('workouts','2026-09-01',raw,'Asia/Shanghai'),[])
    index=AnalyticsStore(store,'Asia/Shanghai');index.rebuild_all()
    row=trends(index,'2026-09-01','2026-09-01')['days'][0]
    assert row['activity']=={} and row['workout_activity']=={'outdoor_cycling':10}
    assert index.activities('2026-01-01','2026-12-31',source='workout')['total']==1
    assert index.activities('2026-01-01','2026-12-31',source='band_episode')['total']==0
    assert index.activities('2026-01-01','2026-12-31',type='walking')['total']==0


def test_partial_archive_locks_account_identity(tmp_path):
    store=Store(tmp_path/'test.db')
    settings=Settings(tmp_path,{'ADMIN_PASSWORD':'test-password-long','ZEPP_USER_ID':'111','ZEPP_TOKEN':'fixture'})
    store.archive_raw('2026-09-01','workout_page',page(123))
    assert store.has_data()
    with pytest.raises(ValueError): settings.update({'user_id':'222'},has_data=store.has_data())


def test_force_resets_stuck_pagination_without_touching_running_task(tmp_path):
    store=Store(tmp_path/'test.db');store.enqueue(['2026-09-01'],['workouts'])
    store.checkpoint_workout_page('2026-09-01',page(123),{})
    store.finish({'day':'2026-09-01','kind':'workouts'},'failed','stuck')
    store.enqueue(['2026-09-01'],['workouts'],True,reset_workouts=True)
    assert store.workout_checkpoint('2026-09-01') is None
    store.checkpoint_workout_page('2026-09-01',page(123),{})
    store.claim()
    store.enqueue(['2026-09-01'],['workouts'],True,reset_workouts=True)
    assert store.workout_checkpoint('2026-09-01')['cursor']==123


def test_normal_schedule_retry_preserves_workout_checkpoint(tmp_path):
    store=Store(tmp_path/'test.db');store.enqueue(['2026-09-01'],['workouts'])
    store.checkpoint_workout_page('2026-09-01',page(123),{})
    store.finish({'day':'2026-09-01','kind':'workouts'},'failed','network')
    store.enqueue(['2026-09-01'],['workouts'],True)
    assert store.workout_checkpoint('2026-09-01')['cursor']==123
