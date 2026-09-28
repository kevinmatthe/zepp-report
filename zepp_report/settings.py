"""Validated local settings; secret fields never enter public responses."""
import json
import math
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .client import REGIONS

DEFAULTS = {'user_id':'', 'token':'', 'region':'global', 'timezone':'Asia/Shanghai',
            'interval_minutes':30, 'initial_days':30, 'lookback_days':3}


class Settings:
    def __init__(self, directory, environ=None):
        env = os.environ if environ is None else environ
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory/'settings.json'
        self.lock = threading.RLock()
        self.password = env.get('ADMIN_PASSWORD','')
        if len(self.password) < 12:
            raise ValueError('ADMIN_PASSWORD 必须至少 12 个字符')
        self.account = env.get('ZEPP_ACCOUNT','personal')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',self.account):
            raise ValueError('ZEPP_ACCOUNT must be a short ASCII identifier')
        self.vm_url = env.get('VM_IMPORT_URL','http://zepp-vm:8428/api/v1/import')
        parsed = urlsplit(self.vm_url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('VM_IMPORT_URL 必须是不含凭据和查询参数的 HTTP(S) 地址')
        self.vm_query_url = env.get('VM_QUERY_URL','').rstrip('/')
        if self.vm_query_url:
            parsed=urlsplit(self.vm_query_url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('VM_QUERY_URL 必须是不含凭据和查询参数的 HTTP(S) 地址')
        retention=env.get('VM_RETENTION_DAYS','')
        self.vm_retention_days=int(retention) if retention else None
        if self.vm_retention_days is not None and not 1<=self.vm_retention_days<=36500:
            raise ValueError('VM_RETENTION_DAYS 必须为 1–36500')
        self.vm_dedup_seconds=float(env.get('VM_DEDUP_INTERVAL_SECONDS','0'))
        if not math.isfinite(self.vm_dedup_seconds) or not 0<=self.vm_dedup_seconds<=3600:
            raise ValueError('VM_DEDUP_INTERVAL_SECONDS 必须为 0–3600')
        self.vm_token = env.get('VM_BEARER_TOKEN','')
        self.cookie_secure = env.get('COOKIE_SECURE','true').lower() == 'true'
        self._values = DEFAULTS.copy()
        if self.path.exists():
            self._values.update(json.loads(self.path.read_text()))
            os.chmod(self.path,0o600)
        else:
            for key in ('user_id','token','region','timezone'):
                if env.get('ZEPP_'+key.upper()):
                    self._values[key] = env['ZEPP_'+key.upper()]
        self.validate(self._values)

    @staticmethod
    def validate(values):
        if set(values) - set(DEFAULTS):
            raise ValueError('不支持的配置字段')
        if values['region'] not in REGIONS:
            raise ValueError('区域必须为 global、us 或 eu')
        if not isinstance(values['user_id'],str) or (values['user_id'] and not re.fullmatch(r'[0-9]{1,30}',values['user_id'])):
            raise ValueError('用户 ID 必须是数字')
        if not isinstance(values['token'],str) or len(values['token']) > 8192 or any(c.isspace() for c in values['token']):
            raise ValueError('Token 格式无效')
        try:
            ZoneInfo(values['timezone'])
        except (ZoneInfoNotFoundError,TypeError,ValueError):
            raise ValueError('时区无效') from None
        for field,low,high in (('interval_minutes',5,1440),('initial_days',1,3650),('lookback_days',2,30)):
            if type(values[field]) is not int or not low <= values[field] <= high:
                raise ValueError(f'{field} 必须为 {low}–{high} 的整数')

    def snapshot(self):
        with self.lock:
            return self._values.copy()

    def public(self):
        result=self.snapshot()
        result['token_configured']=bool(result.pop('token'))
        result['configured']=bool(result['user_id'] and result['token_configured'])
        result.update(account=self.account,vm_url=self.vm_url,vm_query_url=self.vm_query_url,vm_retention_days=self.vm_retention_days,vm_dedup_seconds=self.vm_dedup_seconds)
        return result

    def update(self, changes, has_data):
        with self.lock:
            changes=changes.copy()
            if changes.get('token') == '':
                changes.pop('token')
            values=dict(self._values,**changes)
            self.validate(values)
            if has_data and any(values[k] != self._values[k] for k in ('user_id','timezone','region')):
                raise ValueError('已有归档时不能更换账号、区域或时区；请使用独立数据目录')
            temp=self.path.with_suffix('.tmp')
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump(values,stream,ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp,self.path)
            os.chmod(self.path,0o600)
            directory_fd=os.open(self.directory,os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._values=values
            return self.public()
