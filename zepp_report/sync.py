"""One recoverable scheduler, persistent per-day checkpoints and VM retries."""
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import threading
import time
from zoneinfo import ZoneInfo
import requests
from .client import AuthError, UpstreamError, ZeppClient
from .normalize import KINDS, normalize
from .metrics import metric_lines, sample_lines, json_lines


def dates(start,end):
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    return [(a+timedelta(days=i)).isoformat() for i in range((b-a).days+1)]


class SyncService:
    def __init__(self,settings,store,client_factory=ZeppClient,transport=None):
        self.settings,self.store=settings,store
        self.client_factory=client_factory
        self.transport=transport or requests.Session()
        self.stop_event=threading.Event()
        self.operation=threading.RLock()
        self.thread=None
        self.lock_file=None
        self.next_flush=0
        self.vm_failures=0
        self.vm_error=None
        self.worker_error=None
        self.next_telemetry=0

    def schedule(self):
        with self.operation:
            if not self.settings.public()['configured']:
                return 0
            cfg=self.settings.snapshot()
            today=datetime.now(ZoneInfo(cfg['timezone'])).date()
            initial=not self.store.meta('initialized',False)
            days=cfg['initial_days'] if initial else cfg['lookback_days']
            queued=self.store.enqueue(dates((today-timedelta(days=days-1)).isoformat(),today.isoformat()),KINDS)
            self.store.retry_failed()
            self.store.set_meta('initialized',True)
            self.store.set_meta('next_sync',time.time()+cfg['interval_minutes']*60)
            return queued

    def credentials_changed(self):
        with self.operation:
            self.store.resume_auth()

    def credential_fingerprint(self):
        cfg=self.settings.snapshot()
        return hashlib.sha256(json.dumps([cfg[k] for k in ('user_id','region','token')]).encode()).hexdigest()

    def tick(self):
        with self.operation:
            if self.store.meta('auth_required',False) and self.store.meta('auth_fingerprint') != self.credential_fingerprint():
                self.credentials_changed()
            if not self.settings.public()['configured'] or self.store.meta('auth_required',False):
                return False
            task=self.store.claim()
            if task is None:
                return False
            cfg=self.settings.snapshot()
            try:
                raw=self.client_factory(cfg).fetch(task['kind'],task['day'])
                self.store.archive_raw(task['day'],task['kind'],raw)
                data=normalize(task['kind'],task['day'],raw,cfg['timezone'])
                lines=metric_lines(task['day'],data,self.settings.account,cfg['timezone'])
                self.store.save(task['day'],task['kind'],raw,data,lines)
            except AuthError:
                self.store.finish(task,'failed','Zepp Token 已失效，请更新凭据')
                self.store.set_meta('auth_fingerprint',self.credential_fingerprint())
                self.store.set_meta('auth_required',True)
            except UpstreamError as exc:
                self.store.finish(task,'failed',str(exc))
            except (ValueError,TypeError,KeyError,OverflowError):
                self.store.finish(task,'failed','数据格式无法解析；任务保留，可重试')
            except Exception:
                self.store.finish(task,'failed','同步内部错误；任务保留，可重试')
            return True

    def telemetry(self):
        if time.monotonic()<self.next_telemetry:
            return
        stats=self.store.stats()
        values={'pending_tasks':stats['tasks']['pending'], 'failed_tasks':stats['tasks']['failed'],
                'auth_required':int(self.store.meta('auth_required',False)),
                'pending_exports':stats['pending_exports'],'conflicts':stats['conflicts']}
        last_success=self.store.meta('last_success')
        if last_success is not None:
            values['last_success_timestamp_seconds']=last_success
        self.store.telemetry([{'metric':{'__name__':'zepp_sync_'+key,'account':self.settings.account},
                               'values':[value],'timestamps':[int(time.time()*1000)]} for key,value in values.items()])
        self.next_telemetry=time.monotonic()+60

    def flush(self,force=False):
        if not force and time.monotonic() < self.next_flush:
            return
        rows=self.store.pending()
        if not rows:
            return
        ids=[r['id'] for r in rows]
        self.store.attempted(ids)
        headers={'Content-Type':'application/json'}
        if self.settings.vm_token:
            headers['Authorization']='Bearer '+self.settings.vm_token
        try:
            response=self.transport.post(self.settings.vm_url, data=json_lines(sample_lines(rows)).encode(),
                headers=headers,timeout=(10,30),allow_redirects=False)
            if response.status_code not in (200,204):
                raise UpstreamError(f'VictoriaMetrics HTTP {response.status_code}')
        except (requests.RequestException,UpstreamError):
            self.vm_failures+=1
            self.vm_error='VictoriaMetrics 写入失败，数据已保留并将自动重试'
            self.next_flush=time.monotonic()+min(300,2**min(self.vm_failures,8))
            return
        self.store.ack(ids)
        self.vm_error=None
        self.vm_failures=0
        self.next_flush=0

    def status(self):
        return dict(self.store.stats(), configured=self.settings.public()['configured'],
            auth_required=self.store.meta('auth_required',False),
            worker_alive=bool(self.thread and self.thread.is_alive()),
            last_success=self.store.meta('last_success'),next_sync=self.store.meta('next_sync'),
            vm_error=self.vm_error,worker_error=self.worker_error)

    def run(self):
        recover_needed=False
        while not self.stop_event.is_set():
            try:
                if recover_needed:
                    self.store.recover()
                    recover_needed=False
                if not self.store.meta('auth_required',False) and time.time() >= self.store.meta('next_sync',0):
                    self.schedule()
                worked=self.tick()
                self.telemetry()
                self.flush()
                self.worker_error=None
                self.stop_event.wait(0.3 if worked else 2)
            except Exception:
                # Keep the worker recoverable even if disk/transport briefly fails.
                recover_needed=True
                self.worker_error='后台处理失败，正在重试；请检查数据目录空间与权限'
                self.stop_event.wait(5)

    def start(self):
        self.lock_file=open(self.settings.directory/'worker.lock','a')
        try:
            fcntl.flock(self.lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            raise RuntimeError('此数据目录已有同步进程；请使用单实例、单 worker') from None
        self.store.recover()
        self.thread=threading.Thread(target=self.run,name='zepp-sync',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=45)
        # Do not release singleton lock while an in-flight worker still owns state.
        if self.lock_file and not (self.thread and self.thread.is_alive()):
            self.lock_file.close()
