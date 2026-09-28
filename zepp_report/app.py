"""Authenticated same-origin API and dashboard."""
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from .settings import Settings
from .store import Store
from .sync import SyncService, dates
from .normalize import KINDS
from .metrics import metric_lines, json_lines, ADDITIONAL_SUMMARY_KEYS
from . import analytics
from .coverage import coverage, preview


class Login(BaseModel):
    password: str = Field(max_length=1024)


class SettingsChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token: str | None = Field(default=None,max_length=8192)
    user_id: str | None = Field(default=None,max_length=30)
    region: str | None = None
    timezone: str | None = Field(default=None,max_length=100)
    interval_minutes: StrictInt | None = None
    initial_days: StrictInt | None = None
    lookback_days: StrictInt | None = None


class SyncRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    from_date: date | None = None
    to_date: date | None = None
    force: StrictBool = False
    kinds: list[Literal['band','stress','training','trimp','sport','vo2','workouts','spo2']] | None = Field(default=None,min_length=1,max_length=8)


def create_app(data_dir=None,environ=None,start_worker=True):
    env=os.environ if environ is None else environ
    settings=Settings(data_dir or env.get('DATA_DIR','./data'),env)
    store=Store(settings.directory/'zepp.sqlite3')
    service=SyncService(settings,store)
    sessions={}
    attempts=deque()
    auth_lock=threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            service.start()
        yield
        if start_worker:
            service.stop()

    app=FastAPI(title='Zepp Report',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.service=service
    app.state.settings=settings
    app.state.store=store

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        # FastAPI's default errors include submitted input, including Token/password.
        return JSONResponse({'detail':'请求参数无效，请检查字段类型、日期及长度'},status_code=422)

    @app.middleware('http')
    async def guard(request:Request,call_next):
        path=request.url.path
        if path.startswith('/api/'):
            if request.method not in ('GET','HEAD'):
                if request.headers.get('x-zepp-request') != '1':
                    return JSONResponse({'detail':'缺少同源请求标识'},status_code=403)
                origin=request.headers.get('origin')
                if origin and (urlsplit(origin).scheme not in ('http','https') or urlsplit(origin).netloc != request.url.netloc):
                    return JSONResponse({'detail':'不允许跨站请求'},status_code=403)
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>32768:
                        return JSONResponse({'detail':'请求内容过大'},status_code=413)
                request._body=bytes(body)
            if path != '/api/login':
                token=request.cookies.get('zepp_session','')
                with auth_lock:
                    valid=sessions.get(token,0)>time.time()
                if not valid:
                    return JSONResponse({'detail':'请先登录'},status_code=401)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    def validate_range(start,end,limit=366):
        cfg=settings.snapshot()
        today=datetime.now(ZoneInfo(cfg['timezone'])).date()
        if start>end or (end-start).days>=limit or start<date(1970,1,1) or end>today:
            raise HTTPException(422,f'日期范围必须在 1970-01-01 至今天内，且不超过 {limit} 天')
        return start.isoformat(),end.isoformat()

    @app.get('/healthz')
    def health():
        alive=not start_worker or bool(service.thread and service.thread.is_alive())
        return JSONResponse({'status':'ok' if alive else 'worker_stopped'},status_code=200 if alive else 503)

    @app.post('/api/login')
    def login(body:Login):
        now=time.time()
        with auth_lock:
            while attempts and attempts[0]<now-60:
                attempts.popleft()
            if len(attempts)>=10:
                raise HTTPException(429,'登录尝试过于频繁，请稍后重试')
            if not hmac.compare_digest(hashlib.sha256(body.password.encode()).digest(),hashlib.sha256(settings.password.encode()).digest()):
                attempts.append(now)
                raise HTTPException(401,'密码不正确')
            for key,expiry in list(sessions.items()):
                if expiry<=now:
                    del sessions[key]
            if len(sessions)>=128:
                del sessions[next(iter(sessions))]
            token=secrets.token_urlsafe(32)
            sessions[token]=now+12*3600
        response=JSONResponse({'ok':True})
        response.set_cookie('zepp_session',token,max_age=12*3600,httponly=True,secure=settings.cookie_secure,samesite='strict')
        return response

    @app.post('/api/logout')
    def logout(request:Request):
        with auth_lock:
            sessions.pop(request.cookies.get('zepp_session',''),None)
        response=JSONResponse({'ok':True})
        response.delete_cookie('zepp_session')
        return response

    @app.get('/api/settings')
    def get_settings():
        return settings.public()

    @app.put('/api/settings')
    def update_settings(body:SettingsChange):
        changes=body.model_dump(exclude_none=True)
        with service.operation:
            before=settings.snapshot()
            try:
                result=settings.update(changes,has_data=store.has_data())
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from None
            after=settings.snapshot()
            if changes.get('token') or any(before[k]!=after[k] for k in ('token','user_id','region')):
                service.credentials_changed()
            elif before['interval_minutes']!=after['interval_minutes']:
                store.set_meta('next_sync',time.time()+after['interval_minutes']*60)
            return result

    @app.get('/api/status')
    def status():
        return service.status()

    @app.post('/api/sync')
    def sync(body:SyncRequest):
        cfg=settings.snapshot()
        if not settings.public()['configured']:
            raise HTTPException(409,'请先配置 Zepp 用户 ID 和 Token')
        if (body.from_date is None)!=(body.to_date is None):
            raise HTTPException(422,'开始和结束日期必须同时填写')
        manual=body.from_date is not None
        today=datetime.now(ZoneInfo(cfg['timezone'])).date()
        start,end=validate_range(body.from_date or today-timedelta(days=cfg['lookback_days']-1),body.to_date or today,3650)
        queued=store.enqueue(dates(start,end),body.kinds or KINDS,include_done=body.force or not manual,reset_workouts=body.force)
        return {'queued':queued}

    @app.post('/api/retry')
    def retry(body:SyncRequest | None = None):
        if store.meta('auth_required',False):
            raise HTTPException(409,'请先更新已失效的 Zepp Token，然后继续回溯')
        start=end=None
        if body and (body.from_date is not None or body.to_date is not None):
            if body.from_date is None or body.to_date is None:
                raise HTTPException(422,'开始和结束日期必须同时填写')
            start,end=validate_range(body.from_date,body.to_date,3650)
        count=store.retry_failed(start,end,body.kinds if body else None)
        return {'queued':count}

    @app.post('/api/sync/preview')
    def sync_preview(body:SyncRequest):
        if body.from_date is None or body.to_date is None:
            raise HTTPException(422,'请指定开始和结束日期')
        start,end=validate_range(body.from_date,body.to_date,3650)
        return preview(store,start,end,tuple(dict.fromkeys(body.kinds or KINDS)),body.force)

    @app.get('/api/coverage')
    def get_coverage(from_date:date,to_date:date,kind:Literal['band','stress','training','trimp','sport','vo2','workouts','spo2']|None=None):
        if from_date>to_date or (to_date-from_date).days>=366 or from_date<date(1970,1,1):
            raise HTTPException(422,'覆盖日历范围不能超过366天')
        return coverage(store,from_date.isoformat(),to_date.isoformat(),settings.snapshot()['timezone'],kind,
                        include_tasks=(to_date-from_date).days<31)

    @app.get('/api/tasks')
    def get_tasks(from_date:date,to_date:date,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),
                  kind:Literal['band','stress','training','trimp','sport','vo2','workouts','spo2']|None=None,
                  status:Literal['pending','running','failed','done']|None=None):
        start,end=validate_range(from_date,to_date,3650)
        where='day BETWEEN ? AND ?'; params=[start,end]
        if kind:
            where+=' AND kind=?'; params.append(kind)
        if status:
            where+=' AND status=?'; params.append(status)
        with store.connect() as con:
            total=con.execute('SELECT count(*) FROM tasks WHERE '+where,params).fetchone()[0]
            items=[dict(r) for r in con.execute('SELECT * FROM tasks WHERE '+where+' ORDER BY day DESC,kind LIMIT ? OFFSET ?',params+[limit,offset])]
        return {'tasks':items,'total':total,'limit':limit,'offset':offset}

    @app.get('/api/analytics/trends')
    def get_trends(from_date:date,to_date:date,compare:Literal['none','previous','year']='none',grain:Literal['day','week','month']='day'):
        start,end=validate_range(from_date,to_date)
        return analytics.trends(service.analytics,start,end,compare,grain)

    @app.get('/api/analytics/profile')
    def get_profile(from_date:date,to_date:date,metric:Literal['heart_rate','stress','spo2']='heart_rate'):
        start,end=validate_range(from_date,to_date)
        return analytics.profile(service.analytics,start,end,metric)

    @app.get('/api/days/{day}')
    def get_day(day:date):
        start,_=validate_range(day,day)
        return service.analytics.detail(start)

    @app.get('/api/activities')
    def get_activities(from_date:date,to_date:date,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),type:str|None=None,source:Literal['band_episode','workout']|None=None):
        start,end=validate_range(from_date,to_date,366)
        return service.analytics.activities(start,end,limit,offset,type,source)

    @app.get('/api/data')
    def data(from_date:date,to_date:date):
        start,end=validate_range(from_date,to_date)
        return {'timezone':settings.snapshot()['timezone'],'days':store.days(start,end)}

    @app.get('/api/export')
    def export(from_date:date,to_date:date):
        start,end=validate_range(from_date,to_date,3650)
        cfg=settings.snapshot()
        def generate():
            for day in dates(start,end):
                for record in store.days(day,day):
                    detail=service.analytics.detail(day)
                    record['steps']=detail['steps']
                    record['summary'].update({k:detail['summary'][k] for k in ADDITIONAL_SUMMARY_KEYS if k in detail['summary']})
                    yield json_lines(metric_lines(day,record,settings.account,cfg['timezone'],archive=True))
        return StreamingResponse(generate(),media_type='application/x-ndjson',
            headers={'Content-Disposition':f'attachment; filename="zepp-{start}-{end}.jsonl"'})

    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')
    @app.get('/')
    def index():
        return FileResponse(static/'index.html')
    @app.get('/beta')
    @app.get('/beta/', include_in_schema=False)
    def beta():
        return FileResponse(static/'beta.html', headers={'Cache-Control':'no-cache'})
    return app
