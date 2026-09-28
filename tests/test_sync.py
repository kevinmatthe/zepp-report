import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from zepp_report.settings import Settings
from zepp_report.store import Store
from zepp_report.sync import SyncService
from zepp_report.client import AuthError
from zepp_report.metrics import metric_lines


def setup(tmp_path):
    settings=Settings(tmp_path, {'ADMIN_PASSWORD':'test-password-long', 'VM_IMPORT_URL':'http://vm:8428/api/v1/import'})
    settings.update({'user_id':'123','token':'secret'}, has_data=False)
    store=Store(tmp_path/'db.sqlite3')
    return settings,store


class Client:
    def fetch(self,kind,day):
        if kind=='band': return {'code':1,'data':[]}
        return {'items':[]}


class VM:
    def __init__(self, fail=False): self.fail,self.payloads=fail,[]
    def post(self,url,**kw):
        self.payloads.append(kw['data'])
        if self.fail: raise requests.ConnectionError()
        class Response: status_code=204
        return Response()


def test_first_backfill_and_worker_store_empty_results(tmp_path):
    settings,store=setup(tmp_path)
    service=SyncService(settings,store,client_factory=lambda _:Client(),transport=VM())
    count=service.schedule()
    assert count == 30*6
    assert service.tick()
    assert store.stats()['tasks']['done']==1


def test_auth_failure_pauses_then_token_update_resumes(tmp_path):
    settings,store=setup(tmp_path)
    class Expired:
        def fetch(self,*args): raise AuthError('Zepp Token 已失效')
    service=SyncService(settings,store,client_factory=lambda _:Expired(),transport=VM())
    store.enqueue(['2026-09-27'],['band'])
    service.tick()
    assert service.status()['auth_required']
    assert not service.tick()
    settings.update({'token':'new-secret'},has_data=False)
    service.credentials_changed()
    service.client_factory=lambda _:Client()
    assert service.tick()
    assert not service.status()['auth_required']


def test_vm_outage_keeps_pending_then_retry_acks(tmp_path):
    settings,store=setup(tmp_path)
    line={'metric':{'__name__':'zepp_steps_daily','account':'personal'},'values':[123],'timestamps':[1000]}
    store.save('2026-09-27','band',{}, {'summary':{'steps':123}},[line])
    vm=VM(fail=True)
    service=SyncService(settings,store,transport=vm)
    service.flush()
    assert len(store.pending())==1
    assert service.status()['vm_error']
    vm.fail=False
    service.flush(force=True)
    assert store.pending()==[]
    assert json.loads(vm.payloads[-1].splitlines()[0])==line


def test_daily_and_current_have_distinct_names_and_times():
    now=datetime(2026,9,28,10,tzinfo=ZoneInfo('Asia/Shanghai'))
    data={'summary':{'steps':400},'heart_rate':[{'time':1790438400000,'value':70}]}
    lines=metric_lines('2026-09-27',data,'personal','Asia/Shanghai',now)
    assert next(x for x in lines if x['metric']['__name__']=='zepp_steps_daily')['timestamps']==[1790438400000]
    current=metric_lines('2026-09-28',data,'personal','Asia/Shanghai',now)
    assert 'zepp_steps_daily' not in {x['metric']['__name__'] for x in current}
    assert next(x for x in current if x['metric']['__name__']=='zepp_steps_current')['timestamps']==[int(now.timestamp()*1000)]


def test_bad_decode_fails_task_without_empty_archive(tmp_path):
    settings,store=setup(tmp_path)
    class Bad:
        def fetch(self,*args): return {'data':[{'date_time':'2026-09-27','summary':'!'}]}
    service=SyncService(settings,store,client_factory=lambda _:Bad(),transport=VM())
    store.enqueue(['2026-09-27'],['band'])
    service.tick()
    assert store.stats()['tasks']['failed']==1
    assert store.days('2026-09-27','2026-09-27')==[]


def test_decode_failure_preserves_raw_for_recovery(tmp_path):
    settings,store=setup(tmp_path)
    raw={'data':[{'date_time':'2026-09-27','summary':'!'}]}
    class Bad:
        def fetch(self,*args): return raw
    service=SyncService(settings,store,client_factory=lambda _:Bad(),transport=VM())
    store.enqueue(['2026-09-27'],['band'])
    service.tick()
    with store.connect() as con:
        saved=con.execute('SELECT raw FROM raw_versions').fetchone()
    assert saved is not None and json.loads(saved[0])==raw


def test_restart_with_vm_backlog_preserves_health_archive(tmp_path):
    settings,store=setup(tmp_path)
    store.save('2026-09-27','band',{}, {'summary':{'steps':22}},[
        {'metric':{'__name__':'zepp_steps_daily','account':'personal'},'values':[22],'timestamps':[1000]}])
    service=SyncService(settings,store,transport=VM(fail=True))
    service.flush()
    restarted=SyncService(settings,Store(tmp_path/'db.sqlite3'),transport=VM())
    restarted.flush()
    assert restarted.store.stats()['pending_exports']==0
    assert restarted.store.days('2026-09-27','2026-09-27')[0]['summary']['steps']==22


def test_crash_after_token_file_write_recovers_on_restart(tmp_path):
    settings,store=setup(tmp_path)
    class Expired:
        def fetch(self,*args): raise AuthError('Token')
    first=SyncService(settings,store,client_factory=lambda _:Expired(),transport=VM())
    store.enqueue(['2026-09-27'],['band'])
    first.tick()
    assert store.meta('auth_required')
    # Crash after file replacement, before app's credentials_changed callback.
    settings.update({'token':'replacement'},has_data=False)
    restarted=SyncService(settings,Store(tmp_path/'db.sqlite3'),client_factory=lambda _:Client(),transport=VM())
    assert restarted.tick()
    assert not restarted.status()['auth_required']
    assert restarted.store.stats()['tasks']['done']==1


def test_transient_database_failure_does_not_strand_running_task(tmp_path):
    import sqlite3
    import threading
    settings,store=setup(tmp_path)
    service=SyncService(settings,store,client_factory=lambda _:Client(),transport=VM())
    store.set_meta('next_sync',9999999999)
    store.enqueue(['2026-09-27'],['band'])
    original_save=store.archive_raw
    original_finish=store.finish
    attempts=[]
    def flaky_archive(*args):
        attempts.append(1)
        if len(attempts)==1: raise sqlite3.OperationalError('disk full')
        original_save(*args)
    def flaky_finish(*args):
        if len(attempts)==1: raise sqlite3.OperationalError('disk full')
        return original_finish(*args)
    store.archive_raw=flaky_archive
    store.finish=flaky_finish
    # Stop after a few worker iterations without real sleeps.
    class Stop:
        def __init__(self): self.count=0
        def is_set(self): return self.count>=3
        def wait(self,_): self.count+=1
    service.stop_event=Stop()
    service.run()
    assert store.stats()['tasks']['running']==0
    assert store.stats()['tasks']['done']==1
