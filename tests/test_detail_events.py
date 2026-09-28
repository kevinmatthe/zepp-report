from zepp_report.normalize import normalize, day_ms
from zepp_report.analytics_store import AnalyticsStore
from zepp_report.store import Store


def test_event_detail_keeps_intraday_points_and_signed_balance(tmp_path):
    day='2026-09-01'; ts=day_ms(day,'Asia/Shanghai')
    raw={'items':[{'timestamp':ts+7200000,'value':{'atl':22,'ctl':11,'tsb':-11}},
                  {'timestamp':ts+3600000,'value':{'atl':20,'ctl':12,'tsb':-8}}]}
    data=normalize('training',day,raw,'Asia/Shanghai')
    assert data['event_series']['tsb']==[{'time':ts+3600000,'value':-8},{'time':ts+7200000,'value':-11}]
    assert data['summary']['atl']==22
    store=Store(tmp_path/'archive.db')
    # Existing archives predate the new derived fields; detail must reparse raw.
    store.save(day,'training',raw,{'summary':{'atl':22}},[])
    detail=AnalyticsStore(store,'Asia/Shanghai').detail(day)
    assert detail['event_series']==data['event_series']


def test_day_id_without_timestamp_does_not_invent_intraday_observation():
    data=normalize('sport','2026-09-01',{'items':[{'dayId':'2026-09-01','currnetDayTrainLoad':42}]},'Asia/Shanghai')
    assert data['summary']['sport_load']==42
    assert data['event_series']=={}
