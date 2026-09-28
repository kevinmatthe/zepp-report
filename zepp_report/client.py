"""Bounded, retrying Zepp requests; responses never enter errors or logs."""
import time
from datetime import date, timedelta
import requests
from .normalize import day_bounds

REGIONS = {'global': 'https://api-mifit.huami.com', 'us': 'https://api-mifit-us2.zepp.com', 'eu': 'https://api-mifit-de2.zepp.com'}


class UpstreamError(Exception):
    pass


class AuthError(UpstreamError):
    pass


class ZeppClient:
    def __init__(self, settings, transport=None, sleep=time.sleep):
        self.settings = settings
        self.transport = transport or requests.Session()
        self.sleep = sleep

    def request(self, path, params, band=False):
        headers = {'apptoken':self.settings['token'], 'appPlatform':'web' if band else 'ios_phone',
                   'appname':'com.xiaomi.hm.health' if band else 'com.huami.midong',
                   'v':'2.0', 'timezone':self.settings['timezone']}
        for attempt in range(3):
            try:
                response = self.transport.get(REGIONS[self.settings['region']] + path,
                    params=params, headers=headers, timeout=(10,30), allow_redirects=False)
            except requests.RequestException:
                if attempt == 2:
                    raise UpstreamError('Zepp 网络请求失败（已重试）') from None
                self.sleep(2**attempt)
                continue
            if response.status_code in (401,403):
                raise AuthError('Zepp Token 已失效，请更新凭据')
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    self.sleep(2**attempt)
                    continue
            if response.status_code != 200:
                raise UpstreamError(f'Zepp HTTP {response.status_code}')
            try:
                body = response.json()
            except ValueError:
                raise UpstreamError('Zepp 返回无效 JSON') from None
            if not isinstance(body, dict):
                raise UpstreamError('Zepp 返回结构异常')
            if body.get('code') in (401,403,-401,-403):
                raise AuthError('Zepp Token 已失效，请更新凭据')
            if ('code' in body and body['code'] not in (0,1,200)) or (band and body.get('code') != 1):
                raise UpstreamError('Zepp 业务接口返回错误')
            key = 'data' if band else 'items'
            if not isinstance(body.get(key), list):
                raise UpstreamError(f'Zepp 响应缺少 {key} 数组')
            return body
        raise UpstreamError('Zepp 请求失败')

    def fetch(self, kind, day):
        uid = self.settings['user_id']
        low, high = day_bounds(day, self.settings['timezone'])
        if kind == 'band':
            return self.request('/v1/data/band_data.json', {'userid':uid, 'query_type':'detail',
                'device_type':'android_phone','from_date':(date.fromisoformat(day)-timedelta(days=1)).isoformat(),
                'to_date':day}, band=True)
        if kind in ('sport','vo2'):
            metric = 'SPORT_LOAD' if kind == 'sport' else 'VO2_MAX'
            body = self.request(f'/v2/watch/users/{uid}/WatchSportStatistics/{metric}',
                {'startDay':day,'endDay':day,'limit':900,'isReverse':'true'})
            if len(body['items']) >= 900:
                raise UpstreamError('单日运动记录达到接口上限，未标记同步成功')
            return body
        if kind == 'stress':
            path, params = f'/users/{uid}/events', {'eventType':'all_day_stress'}
        elif kind == 'training':
            path, params = '/v2/users/me/events', {'eventType':'exertion','subType':'algo_result'}
        elif kind == 'trimp':
            path, params = '/v2/users/me/events', {'eventType':'phn','subType':'daily_analysis'}
        else:
            raise ValueError('Unknown data kind')
        pages = []
        def fetch_window(a, b, depth=0):
            body = self.request(path, dict(params, **{'from':a,'to':b,'limit':200}))
            pages.append(body)
            if len(body['items']) < 200:
                return body['items']
            if depth >= 16 or a >= b:
                raise UpstreamError('事件窗口仍达到接口上限，未标记同步成功')
            middle = (a+b)//2
            return fetch_window(a,middle,depth+1) + fetch_window(middle+1,b,depth+1)
        return {'items': fetch_window(low,high-1), '_pages': pages}
