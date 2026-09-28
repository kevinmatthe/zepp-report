#!/usr/bin/env python3
"""Integration test against three isolated VM containers, never the live cluster.
Requires local vmstorage/vminsert/vmselect images and Docker. All created resources
are removed in finally; test storage uses an explicit temporary bind mount.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from zepp_report.settings import Settings
from zepp_report.store import Store
from zepp_report.sync import SyncService
from zepp_report.metrics import metric_lines, json_lines


def docker(*args):
    return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE).strip()


def eventually(check,timeout=30):
    stop=time.monotonic()+timeout
    while time.monotonic()<stop:
        try:
            value=check()
            if value:return value
        except (requests.RequestException,AssertionError,KeyError):
            pass
        time.sleep(.25)
    raise AssertionError('Timed out waiting for isolated VictoriaMetrics')


def main():
    suffix=uuid.uuid4().hex[:10]
    network='zepp-test-'+suffix
    created=[]
    with tempfile.TemporaryDirectory(prefix='zepp-vm-integration-') as directory:
        directory=Path(directory)
        docker('network','create',network)
        try:
            names={part:f'zepp-test-{part}-{suffix}' for part in ('storage','insert','select')}
            for part,image,args in [
                ('storage','vmstorage',['-storageDataPath=/storage','-retentionPeriod=180d','-inmemoryDataFlushInterval=1s','-dedup.minScrapeInterval=15s']),
                ('insert','vminsert',[f'-storageNode={names["storage"]}:8400']),
                ('select','vmselect',[f'-storageNode={names["storage"]}:8401','-dedup.minScrapeInterval=15s'])]:
                cmd=['run','-d','--name',names[part],'--network',network]
                if part=='storage':
                    storage=directory/'storage';storage.mkdir()
                    cmd+=['--mount',f'type=bind,source={storage},target=/storage']
                # Use exactly a locally available image, never update production images.
                image_id=docker('image','inspect',f'victoriametrics/{image}:latest','--format','{{.Id}}')
                docker(*cmd,image_id,*args)
                created.append(names[part])
            ips={part:docker('inspect',name,'--format',f'{{{{(index .NetworkSettings.Networks "{network}").IPAddress}}}}') for part,name in names.items()}
            # Host proxy settings must never redirect isolated Docker bridge traffic.
            os.environ['NO_PROXY']=','.join(ips.values())
            os.environ['no_proxy']=os.environ['NO_PROXY']
            base=f'http://{ips["select"]}:8481/select/0/prometheus'
            for part,port in [('insert',8480),('select',8481)]:
                eventually(lambda part=part,port=port:requests.get(f'http://{ips[part]}:{port}/health',timeout=2).status_code==200)
            settings=Settings(directory/'app',{'ADMIN_PASSWORD':'integration-test-password',
                'VM_IMPORT_URL':f'http://{ips["insert"]}:8480/insert/0/prometheus/api/v1/import'})
            db=Store(directory/'app'/'db')
            now=datetime.now(ZoneInfo('Asia/Shanghai'))
            yesterday=(now.date()-timedelta(days=1)).isoformat()
            data={'summary':{'steps':1234,'tsb':-7},'heart_rate':[{'time':int(now.timestamp()*1000)-60000,'value':68}]}
            lines=metric_lines(yesterday,data,'personal','Asia/Shanghai',now)
            db.save(yesterday,'band',{},data,lines)
            class LostAcknowledgement:
                def post(self,*args,**kwargs):
                    result=requests.post(*args,**kwargs)
                    assert result.status_code==204
                    raise requests.Timeout('simulated lost acknowledgement')
            first=SyncService(settings,db,transport=LostAcknowledgement())
            first.flush()
            assert db.stats()['pending_exports']==3
            # Simulate application restart after VM accepted a batch but acknowledgement was lost.
            restarted=SyncService(settings,Store(directory/'app'/'db'))
            restarted.flush()
            assert restarted.store.stats()['pending_exports']==0
            def query(expr,at=None):
                r=requests.get(base+'/api/v1/query',params={'query':expr,'time':at or now.timestamp(),'nocache':'1'},timeout=5)
                r.raise_for_status()
                response=r.json()
                assert response['status']=='success',response
                return response['data']['result']
            result=eventually(lambda:query('last_over_time(zepp_steps_daily{account="personal"}[3d])'))
            assert float(result[0]['value'][1])==1234
            result=query('last_over_time(zepp_tsb_daily{account="personal"}[3d])')
            assert float(result[0]['value'][1])==-7
            assert float(query('last_over_time(zepp_heart_rate_bpm{account="personal"}[1h])')[0]['value'][1])==68
            dashboard=json.loads((Path(__file__).resolve().parents[1]/'grafana/dashboards/zepp-health.json').read_text())
            expressions=[]
            for panel in dashboard['panels']:
                for target in panel.get('targets',[]):
                    expr=target.get('expr','').replace('${account:regex}','personal')
                    if expr:
                        query(expr)
                        expressions.append(expr)
            # A missing day must not inherit yesterday's daily value.
            daily=next(expr for expr in expressions if 'zepp_steps_daily' in expr)
            assert query(daily)==[]
            # Current cards should ignore stale snapshots, even if a historical time picker is used.
            stale={'metric':{'__name__':'zepp_steps_current','account':'personal'},'timestamps':[int((now-timedelta(days=1)).timestamp()*1000)],'values':[999]}
            requests.post(settings.vm_url,data=json_lines([stale]),timeout=5).raise_for_status()
            current=next(expr for expr in expressions if 'zepp_steps_current' in expr)
            assert query(current,at=(now-timedelta(days=1)).timestamp())==[]
            data['summary']['steps']=4321
            db.save(yesterday,'band',{},data,metric_lines(yesterday,data,'personal','Asia/Shanghai',now))
            assert db.stats()['conflicts']==1
            assert db.days(yesterday,yesterday)[0]['summary']['steps']==4321
            print(f'PASS: isolated cluster import/query, lost-ack restart recovery, revisions; {len(expressions)} dashboard expressions accepted; missing-day/stale-current checks passed.')
        finally:
            for name in reversed(created):
                subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,check=False)
            subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,check=False)


if __name__=='__main__':main()
