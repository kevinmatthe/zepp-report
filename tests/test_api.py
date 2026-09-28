import pytest
from fastapi.testclient import TestClient
from zepp_report.app import create_app


@pytest.fixture
def client(tmp_path):
    app=create_app(data_dir=tmp_path, environ={'ADMIN_PASSWORD':'test-password-long','COOKIE_SECURE':'false'}, start_worker=False)
    with TestClient(app) as c:
        yield c


def login(client):
    r=client.post('/api/login',json={'password':'test-password-long'},headers={'X-Zepp-Request':'1'})
    assert r.status_code==200
    return {'X-Zepp-Request':'1'}


def test_health_public_data_private_and_password_checked(client):
    assert client.get('/healthz').status_code==200
    assert client.get('/api/data?from_date=2026-09-01&to_date=2026-09-02').status_code==401
    assert client.post('/api/login',json={'password':'wrong'},headers={'X-Zepp-Request':'1'}).status_code==401
    login(client)
    assert client.get('/api/status').status_code==200


def test_settings_token_never_echoed_and_persisted(client):
    headers=login(client)
    r=client.put('/api/settings',json={'token':'private-token','user_id':'123'},headers=headers)
    assert r.status_code==200
    assert r.json()['token_configured']
    assert 'private-token' not in r.text
    assert 'private-token' not in client.get('/api/settings').text
    assert client.put('/api/settings',json={'token':''},headers=headers).json()['token_configured']


def test_write_requires_csrf_header_and_rejects_cross_site(client):
    login(client)
    assert client.post('/api/sync',json={}).status_code==403
    assert client.post('/api/sync',json={},headers={'X-Zepp-Request':'1','Origin':'https://evil.test'}).status_code==403


def test_dates_and_settings_validation(client):
    headers=login(client)
    assert client.get('/api/data?from_date=2026-09-30&to_date=2026-09-01').status_code==422
    assert client.put('/api/settings',json={'region':'unknown'},headers=headers).status_code==422
    assert client.put('/api/settings',json={'interval_minutes':0},headers=headers).status_code==422
    assert client.put('/api/settings',json={'timezone':'No/SuchZone'},headers=headers).status_code==422
    assert client.post('/api/sync',json={},headers=headers).status_code==409


def test_enqueue_and_empty_range(client):
    headers=login(client)
    client.put('/api/settings',json={'token':'secret','user_id':'123'},headers=headers)
    r=client.post('/api/sync',json={'from_date':'2026-09-25','to_date':'2026-09-26'},headers=headers)
    assert r.status_code==200 and r.json()['queued']==12
    assert client.get('/api/data?from_date=2026-09-25&to_date=2026-09-26').json()['days']==[]
    assert client.get('/api/export?from_date=2026-09-25&to_date=2026-09-26').status_code==200


def test_unsafe_admin_password_fails_startup(tmp_path):
    with pytest.raises(ValueError,match='ADMIN_PASSWORD'):
        create_app(data_dir=tmp_path,environ={'ADMIN_PASSWORD':'short'},start_worker=False)


def test_validation_errors_do_not_echo_secrets(client):
    headers=login(client)
    secret='DO-NOT-ECHO-'+('a'*8200)
    r=client.put('/api/settings',json={'token':secret},headers=headers)
    assert r.status_code==422
    assert 'DO-NOT-ECHO' not in r.text
    r=client.post('/api/login',json={'password':secret},headers=headers)
    assert r.status_code==422 and 'DO-NOT-ECHO' not in r.text


def test_same_token_resubmission_can_recover_auth_pause(client):
    headers=login(client)
    client.put('/api/settings',json={'user_id':'123','token':'new-token'},headers=headers)
    client.app.state.store.set_meta('auth_required',True)
    client.put('/api/settings',json={'token':'new-token'},headers=headers)
    assert not client.get('/api/status').json()['auth_required']
