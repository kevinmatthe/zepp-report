from zepp_report.coverage import coverage, preview
from zepp_report.store import Store


def test_coverage_includes_missing_empty_running_and_future(tmp_path):
    store=Store(tmp_path/'test.db')
    store.enqueue(['2026-09-01'],['band','stress'],False)
    store.save('2026-09-01','band',{}, {'summary':{'steps':0}}, [])
    store.save('2026-09-01','stress',{}, {'summary':{}}, [])
    result=coverage(store,'2026-09-01','2026-09-03','Asia/Shanghai',today='2026-09-02')
    a,b,c=result['days']
    assert a['archived']==2 and a['observed']==1 and a['empty']==1
    assert a['status']=='partial' and a['counts']['done']==2
    assert b['status']=='unrequested' and c['status']=='future'
    store.enqueue(['2026-09-01'],['band'],True)
    store.claim()
    a=coverage(store,'2026-09-01','2026-09-01','Asia/Shanghai')['days'][0]
    assert a['status']=='running' and a['archived']==2


def test_preview_and_retry_scoped(tmp_path):
    store=Store(tmp_path/'test.db')
    store.enqueue(['2026-09-01','2026-09-02'],['band'],False)
    for day in ('2026-09-01','2026-09-02'):
        store.finish({'day':day,'kind':'band'},'failed','temporary')
    assert preview(store,'2026-09-01','2026-09-01',['band'])['queued']==1
    assert store.retry_failed('2026-09-01','2026-09-01',['band'])==1
    assert store.stats()['tasks']['failed']==1
