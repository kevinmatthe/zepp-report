from zepp_report.store import Store


def record(steps=123):
    return {'summary': {'steps': steps}, 'heart_rate': [], 'stress': [], 'sleep_stages': []}


def test_upsert_and_queue_are_durable_and_idempotent(tmp_path):
    path = tmp_path / 'db.sqlite3'
    db = Store(path)
    db.save('2026-09-27', 'band', {'data': []}, record(), [{'metric': {'__name__':'zepp_steps_daily','account':'personal'}, 'values':[123], 'timestamps':[1000]}])
    db.save('2026-09-27', 'band', {'data': []}, record(), [{'metric': {'__name__':'zepp_steps_daily','account':'personal'}, 'values':[123], 'timestamps':[1000]}])
    db = Store(path)
    assert len(db.pending()) == 1
    assert db.days('2026-09-27','2026-09-27')[0]['summary']['steps'] == 123
    assert db.raw('2026-09-27','band') == {'data': []}
    db.ack([db.pending()[0]['id']])
    assert db.pending() == []


def test_sent_correction_is_flagged_not_silently_overwritten(tmp_path):
    db = Store(tmp_path/'db')
    def line(value):
        return {'metric': {'__name__':'zepp_steps_daily','account':'personal'},'values':[value],'timestamps':[1000]}
    db.save('2026-09-27','band',{},record(),[line(123)])
    db.ack([db.pending()[0]['id']])
    db.save('2026-09-27','band',{},record(456),[line(456)])
    assert db.pending() == []
    assert db.stats()['conflicts'] == 1
    assert db.days('2026-09-27','2026-09-27')[0]['summary']['steps'] == 456


def test_restart_recovers_claimed_work_and_deduplicates_queue(tmp_path):
    db = Store(tmp_path/'db')
    assert db.enqueue(['2026-09-27'], ['band']) == 1
    assert db.enqueue(['2026-09-27'], ['band']) == 0
    assert db.claim()['day'] == '2026-09-27'
    db.recover()
    assert db.claim()['kind'] == 'band'


def test_day_merges_metrics_from_independent_endpoints(tmp_path):
    db = Store(tmp_path/'db')
    db.save('2026-09-27','band',{},record(),[])
    db.save('2026-09-27','training',{}, {'summary':{'atl':32}},[])
    day = db.days('2026-09-27','2026-09-27')[0]
    assert day['summary'] == {'steps':123,'atl':32}


def test_archive_and_task_checkpoint_commit_together(tmp_path):
    db=Store(tmp_path/'db')
    db.enqueue(['2026-09-27'],['band'])
    task=db.claim()
    db.save(task['day'],task['kind'],{},record(),[])
    # Simulate process death immediately after archive transaction, before returning to worker.
    restarted=Store(tmp_path/'db')
    restarted.recover()
    assert restarted.claim() is None
    assert restarted.stats()['tasks']['done']==1


def test_manual_resume_skips_completed_and_requeues_only_failed(tmp_path):
    db=Store(tmp_path/'db')
    db.enqueue(['2026-09-27'],['band','stress'])
    task=db.claim(); db.finish(task)
    other=db.claim(); db.finish(other,'failed','temporary failure')
    assert db.enqueue(['2026-09-27'],['band','stress'],include_done=False)==1
    assert db.stats()['tasks']['done']==1


def test_uncertain_delivery_revision_keeps_original_for_safe_retry(tmp_path):
    db=Store(tmp_path/'db')
    def line(v): return {'metric':{'__name__':'zepp_steps_daily'},'values':[v],'timestamps':[1000]}
    db.save('2026-09-27','band',{},record(),[line(123)])
    db.attempted([db.pending()[0]['id']])
    db.save('2026-09-27','band',{},record(456),[line(456)])
    assert db.pending()[0]['value']==123
    assert db.stats()['conflicts']==1


def test_retracted_sent_sample_flags_conflict(tmp_path):
    db=Store(tmp_path/'db')
    db.save('2026-09-27','band',{},record(),[{'metric':{'__name__':'zepp_heart_rate_bpm'},'values':[123],'timestamps':[1000]}])
    db.ack([db.pending()[0]['id']])
    db.save('2026-09-27','band',{}, {'summary':{}},[])
    assert db.stats()['conflicts']==1
