import pytest
import requests
from zepp_report.client import ZeppClient, AuthError, UpstreamError


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
    def json(self): return self.body


class Transport:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return result


def client(transport):
    return ZeppClient({'token':'secret','user_id':'123','region':'global','timezone':'Asia/Shanghai'}, transport=transport, sleep=lambda _:None)


def test_auth_expiry_never_leaks_response():
    with pytest.raises(AuthError, match='Token'):
        client(Transport([Response({'secret':'sensitive'},401)])).fetch('band','2026-09-27')


def test_timeout_retries_and_uses_headers_and_timeout():
    transport = Transport([requests.Timeout(),Response({'code':1,'data':[]})])
    assert client(transport).fetch('band','2026-09-27') == {'code':1,'data':[]}
    assert len(transport.calls) == 2
    assert transport.calls[0][1]['timeout'] == (10,30)
    assert transport.calls[0][1]['headers']['timezone'] == 'Asia/Shanghai'


def test_http_200_error_is_not_empty_success():
    with pytest.raises(UpstreamError):
        client(Transport([Response({'code':-50000,'message':'private'})])).fetch('stress','2026-09-27')


def test_events_use_bounded_local_day():
    transport=Transport([Response({'items':[]})])
    client(transport).fetch('training','2026-09-27')
    params=transport.calls[0][1]['params']
    assert params['from'] == 1790438400000
    assert params['to'] == 1790524800000-1


def test_full_page_is_split_without_silent_truncation():
    transport=Transport([Response({'items':[{'timestamp':0}]*200}), Response({'items':[]}),Response({'items':[]})])
    assert client(transport).fetch('stress','2026-09-27')['items'] == []
    assert len(transport.calls) == 3
