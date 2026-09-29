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
    assert r.status_code==200 and r.json()['queued']==16
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


def test_coverage_preview_filtered_retry_and_analytics(client):
    headers=login(client)
    client.put('/api/settings',json={'token':'secret','user_id':'123'},headers=headers)
    body={'from_date':'2026-09-01','to_date':'2026-09-02','kinds':['band']}
    assert client.post('/api/sync/preview',json=body,headers=headers).json()['queued']==2
    assert client.post('/api/sync',json=body,headers=headers).json()['queued']==2
    result=client.get('/api/coverage?from_date=2026-09-01&to_date=2026-09-03').json()
    assert len(result['days'])==3 and result['days'][0]['counts']['pending']==1
    for day in ('2026-09-01','2026-09-02'):
        client.app.state.store.finish({'day':day,'kind':'band'},'failed','test')
    body['to_date']='2026-09-01'
    assert client.post('/api/retry',json=body,headers=headers).json()['queued']==1
    assert client.get('/api/tasks?from_date=2026-09-01&to_date=2026-09-02&limit=1').json()['total']==2
    result=client.get('/api/analytics/trends?from_date=2026-09-01&to_date=2026-09-02').json()
    assert len(result['days'])==2
    result=client.get('/api/analytics/profile?from_date=2026-09-01&to_date=2026-09-02&metric=heart_rate').json()
    assert len(result['buckets'])==288
    assert client.get('/api/days/2026-09-01').json()['date']=='2026-09-01'
    assert client.get('/api/analytics/profile?from_date=2026-09-01&to_date=2026-09-02&metric=oops').status_code==422
    body['kinds']=['oops']
    assert client.post('/api/sync/preview',json=body,headers=headers).status_code==422


def test_coverage_allows_future_grid_but_sync_does_not(client):
    headers=login(client)
    client.put('/api/settings',json={'token':'secret','user_id':'123'},headers=headers)
    assert client.get('/api/coverage?from_date=2099-01-01&to_date=2099-12-31').status_code==200
    assert client.post('/api/sync',json={'from_date':'2099-01-01','to_date':'2099-01-01'},headers=headers).status_code==422


def test_export_adds_minute_steps_without_redefining_legacy_sleep(client):
    import base64,json
    from zepp_report.normalize import normalize,day_ms
    login(client)
    day='2026-09-01';ts=day_ms(day,'Asia/Shanghai')
    summary={'stp':{'ttl':0},'slp':{'st':ts//1000,'ed':ts//1000+5400,
        'stage':[{'start':0,'stop':60,'mode':4},{'start':30,'stop':90,'mode':5}]}}
    raw={'data':[{'date_time':day,'data_type':0,
        'data':base64.b64encode(bytes([1,2,0])*1440).decode(),
        'summary':base64.b64encode(json.dumps(summary).encode()).decode()}]}
    old=normalize('band',day,raw,'Asia/Shanghai');old.pop('steps')
    client.app.state.store.save(day,'band',raw,old,[])
    r=client.get('/api/export',params={'from_date':day,'to_date':day});assert r.status_code==200
    lines={line['metric']['__name__']:line for line in map(json.loads,r.text.splitlines())}
    assert len(lines['zepp_steps_minute']['values'])==1440
    assert lines['zepp_sleep_light_minutes_daily']['values']==[60]
    assert lines['zepp_sleep_deep_minutes_daily']['values']==[60]
    assert 'zepp_sleep_rem_minutes_daily' not in lines


def test_beta_page_is_separate_and_old_home_is_preserved(client):
    old=client.get('/')
    beta=client.get('/beta')
    assert beta.status_code==200
    assert '/static/dist/beta.js' in beta.text
    assert '/static/dist/app.js' in old.text
    assert '/static/dist/beta.js' not in old.text
    assert '返回旧版' in beta.text
    assert client.get('/api/analytics/trends?from_date=2026-09-01&to_date=2026-09-02').status_code==401


def test_beta_manual_percentiles_are_authenticated_and_cache_revalidated(client):
    url='/api/analytics/distributions?from_date=2026-09-01&to_date=2026-09-02'
    assert client.get(url).status_code==401
    login(client)
    result=client.get(url)
    assert result.status_code==200
    assert result.json()['days'][0]['heart_rate']['p35'] is None
    assert client.get('/api/analytics/profile?from_date=2026-09-01&to_date=2026-09-02&full_percentiles=true').json()['buckets'][0]['p35'] is None
    for path in ['/','/beta','/static/beta-bands.js']:
        assert client.get(path).headers['cache-control']=='no-cache'
