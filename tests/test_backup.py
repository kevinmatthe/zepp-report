import json
from zepp_report.admin import backup
from zepp_report.settings import Settings
from zepp_report.store import Store


def test_online_backup_restores_records_tasks_and_settings(tmp_path):
    source=tmp_path/'source'
    settings=Settings(source,{'ADMIN_PASSWORD':'test-password-long'})
    settings.update({'user_id':'123','token':'saved-token'},has_data=False)
    db=Store(source/'zepp.sqlite3')
    db.save('2026-09-27','band',{}, {'summary':{'steps':123}},[])
    db.enqueue(['2026-09-26'],['band'])
    destination=tmp_path/'backup'
    backup(source,destination)
    restored=Store(destination/'zepp.sqlite3')
    assert restored.days('2026-09-27','2026-09-27')[0]['summary']['steps']==123
    assert restored.stats()['tasks']['pending']==1
    assert json.loads((destination/'settings.json').read_text())['token']=='saved-token'
    assert (destination/'settings.json').stat().st_mode & 0o777 == 0o600
