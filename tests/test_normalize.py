import base64
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from zepp_report.normalize import normalize, day_ms


def encoded(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


def test_heart_rate_uses_local_day_and_omits_missing():
    raw = {'data': [{'date_time': '2026-09-27', 'summary': encoded({'stp': {'ttl': 0}}),
                     'data_hr': base64.b64encode(bytes([0, 65, 254, 255, 72])).decode()}]}
    result = normalize('band', '2026-09-27', raw, 'Asia/Shanghai')
    assert result['heart_rate'] == [{'time': 1790438460000, 'value': 65}, {'time': 1790438640000, 'value': 72}]
    assert result['summary'] == {'steps': 0}


def test_sleep_belongs_to_wake_day_and_preserves_stage_timestamps():
    start = int(datetime(2026, 9, 26, 23, 0, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp())
    raw = {'data': [{'date_time': '2026-09-26', 'summary': encoded({'slp': {
        'st': start, 'ed': start + 8*3600, 'ss': 82, 'rhr': 58,
        'stage': [{'start': 1380, 'stop': 1440, 'mode': 5}, {'start': 1440, 'stop': 1860, 'mode': 4}]}})}]}
    result = normalize('band', '2026-09-27', raw, 'Asia/Shanghai')
    assert result['summary']['sleep_minutes'] == 480
    assert result['summary']['sleep_deep_minutes'] == 60
    assert result['sleep_stages'][0] == {'start': start*1000, 'end': (start+3600)*1000, 'stage': 'deep'}
    assert 'steps' not in result['summary']


def test_stress_rejects_sentinels_and_filters_other_dates():
    ts = day_ms('2026-09-27', 'Asia/Shanghai')
    raw = {'items': [{'timestamp': ts, 'avgStress': '32', 'data': json.dumps([
        {'time': ts, 'value': 45}, {'time': ts+300000, 'value': 0},
        {'time': ts+600000, 'value': 255}, {'time': ts-1, 'value': 66}])}]}
    result = normalize('stress', '2026-09-27', raw, 'Asia/Shanghai')
    assert result['stress'] == [{'time': ts, 'value': 45}]
    assert result['summary']['stress_avg'] == 32


def test_training_filters_and_preserves_negative_balance():
    ts = day_ms('2026-09-27', 'Asia/Shanghai')
    result = normalize('training', '2026-09-27', {'items': [
        {'timestamp': ts-86400000, 'value': {'atl': 999}},
        {'timestamp': ts, 'value': {'atl': 42, 'ctl': 37, 'tsb': -5}}]}, 'Asia/Shanghai')
    assert result['summary'] == {'atl': 42, 'ctl': 37, 'tsb': -5}


def test_missing_and_invalid_are_not_zero():
    assert normalize('band', '2026-09-27', {'data': []}, 'Asia/Shanghai')['summary'] == {}
    with pytest.raises(ValueError):
        normalize('band', '2026-09-27', {'data': [{'date_time': '2026-09-27','summary': 'not-base64!'}]}, 'Asia/Shanghai')


def test_dst_day_uses_next_calendar_midnight():
    assert day_ms('2026-03-09', 'America/New_York') - day_ms('2026-03-08', 'America/New_York') == 23*3600000


def test_sleep_stages_anchor_to_sleep_interval_when_row_is_wake_day():
    start=int(datetime(2026,9,26,23,0,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp())
    raw={'data':[{'date_time':'2026-09-27','summary':encoded({'slp':{
        'st':start,'ed':start+8*3600,'stage':[{'start':1380,'stop':1440,'mode':5},
                                         {'start':1440,'stop':1860,'mode':4}]}})}]}
    result=normalize('band','2026-09-27',raw,'Asia/Shanghai')
    assert result['sleep_stages'][0]['start']==start*1000
    assert result['summary']['actual_sleep_minutes']==480
