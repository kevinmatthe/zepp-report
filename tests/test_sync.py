import json
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import pytest
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
    def fetch_workout_page(self,day,cursor=None):
        return {'code':1,'data':{'summary':[],'next':-1}}

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
    assert count == 30*8
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
    assert service.flush() is False
    assert len(store.pending())==1
    assert service.status()['vm_error']
    vm.fail=False
    assert service.flush(force=True) is True
    assert store.pending()==[]
    assert json.loads(vm.payloads[-1].splitlines()[0])==line
    assert service.flush() is False


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


def test_independent_vm_audit_recovers_and_verifies_while_zepp_token_is_expired(tmp_path):
    import threading
    from datetime import timedelta
    from zepp_report.normalize import day_ms

    settings,store=setup(tmp_path)
    settings.vm_query_url='http://vm:8428'
    day=(datetime.now(ZoneInfo(settings.snapshot()['timezone'])).date()-timedelta(days=1)).isoformat()
    line={'metric':{'__name__':'zepp_steps_daily','account':'personal'},'values':[123],
          'timestamps':[day_ms(day,settings.snapshot()['timezone'])]}
    store.save(day,'band',{}, {'summary':{'steps':123}},[line])
    store.attempted([row['id'] for row in store.pending()])
    store.ack([row['id'] for row in store.pending()])
    with store.connect() as con:
        con.execute("UPDATE vm_audits SET state='running',next_check=9999999999")
    service=SyncService(settings,store,client_factory=lambda _:Client(),transport=VM())
    store.set_meta('auth_required',True)
    store.set_meta('auth_fingerprint',service.credential_fingerprint())
    queried=threading.Event()
    class ExportResponse:
        status_code=200
        def iter_content(self,chunk_size):
            yield json.dumps(line).encode()
        def close(self): queried.set()
    class QueryVM:
        def get(self,*args,**kwargs): return ExportResponse()
    service.vm_audit.transport=QueryVM()
    try:
        service.start()
        assert service.audit_thread.is_alive()
        assert queried.wait(3), 'audit did not run independently while Zepp auth was paused'
    finally:
        service.stop()
    status=service.status()
    assert status['auth_required'] is True
    assert status['vm_audit']['states']['verified']==1
    assert status['vm_audit']['missing_samples']==0
    assert not service.audit_thread.is_alive()
    assert service.lock_file.closed


def test_audit_worker_retries_recovery_after_transient_disk_failure(tmp_path):
    import sqlite3
    settings,store=setup(tmp_path)
    service=SyncService(settings,store,transport=VM())
    calls={'tick':0,'recover':0,'schedule':0}
    class Auditor:
        def schedule(self): calls['schedule']+=1
        def tick(self):
            calls['tick']+=1
            if calls['tick']==1: raise sqlite3.OperationalError('disk temporarily unavailable')
            return False
        def recover(self):
            calls['recover']+=1
            if calls['recover']==1: raise sqlite3.OperationalError('still unavailable')
    class Stop:
        count=0
        def is_set(self): return self.count>=3
        def wait(self,_): self.count+=1
    service.vm_audit=Auditor()
    service.stop_event=Stop()
    service.run_audit()
    assert calls=={'tick':2,'recover':2,'schedule':2}
    assert service.audit_worker_error is None


def test_shutdown_uses_shared_budget_and_keeps_lock_until_every_worker_exits(tmp_path,monkeypatch):
    import fcntl
    import zepp_report.sync as sync_module
    settings,store=setup(tmp_path)
    service=SyncService(settings,store,transport=VM())
    clock=[0.0]
    monkeypatch.setattr(sync_module.time,'monotonic',lambda:clock[0])
    budgets=[]
    class Worker:
        def __init__(self,remaining): self.remaining=remaining
        def is_alive(self): return self.remaining>0
        def join(self,timeout):
            budgets.append(timeout)
            elapsed=min(timeout,self.remaining)
            clock[0]+=elapsed
            self.remaining-=elapsed
    service.thread=Worker(40)
    service.analytics_thread=Worker(20)
    service.audit_thread=Worker(30)
    service.lock_file=open(settings.directory/'worker.lock','a')
    fcntl.flock(service.lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        service.stop()
        assert clock[0]<=55
        assert budgets==[55,15,0]
        assert not service.lock_file.closed
        with open(settings.directory/'worker.lock','a') as probe:
            with pytest.raises(BlockingIOError): fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
        service.analytics_thread.remaining=0
        service.audit_thread.remaining=0
        service.stop()
        assert service.lock_file.closed
        with open(settings.directory/'worker.lock','a') as probe:
            fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:
        service.lock_file.close()


@pytest.mark.parametrize('auth_required',[False,True])
@pytest.mark.parametrize('delivery_fails',[False,True])
def test_delivery_progress_controls_idle_wait_without_bypassing_backoff(tmp_path,monkeypatch,auth_required,delivery_fails):
    import zepp_report.sync as sync_module
    settings,store=setup(tmp_path)
    store.save('2026-09-27','band',{}, {'summary':{'steps':123}},[
        {'metric':{'__name__':'zepp_steps_daily','account':'personal'},'values':[123],'timestamps':[1000]}])
    vm=VM(fail=delivery_fails)
    service=SyncService(settings,store,client_factory=lambda _:Client(),transport=vm)
    store.set_meta('next_sync',9999999999)
    store.set_meta('auth_required',auth_required)
    store.set_meta('auth_fingerprint',service.credential_fingerprint())
    service.next_telemetry=float('inf')
    clock=[0.0]
    waits=[]
    monkeypatch.setattr(sync_module.time,'monotonic',lambda:clock[0])
    class Stop:
        def is_set(self): return len(waits)>=3
        def wait(self,seconds):
            waits.append(seconds)
            clock[0]+=seconds
    service.stop_event=Stop()
    service.run()
    assert store.stats()['tasks']['done']==0
    assert store.meta('auth_required') is auth_required
    if delivery_fails:
        assert waits==[2,2,2]
        assert len(vm.payloads)==2  # Third iteration remains within the four-second retry backoff.
        assert service.next_flush==6
        assert len(store.pending())==1
    else:
        assert waits==[.3,2,2]
        assert len(vm.payloads)==1
        assert store.pending()==[]
