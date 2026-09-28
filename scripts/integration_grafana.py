#!/usr/bin/env python3
"""Read-only range regression through an isolated Grafana and the installed VM plugin.

Requires a local Grafana image, plugin directory, existing Docker network and VM
query URL. Never changes the shared Grafana/VM. Temporary container and bind data
are removed even on failure; no host ports are published.
"""
import argparse,json,os,secrets,subprocess,tempfile,time
from pathlib import Path
import requests


def docker(*args):
    return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--plugin-dir',type=Path,required=True)
    parser.add_argument('--network',required=True)
    parser.add_argument('--vm-url',required=True)
    args=parser.parse_args()
    name='zepp-grafana-test-'+secrets.token_hex(4)
    password=secrets.token_urlsafe(24)
    dashboard=json.loads((Path(__file__).resolve().parents[1]/'grafana/dashboards/zepp-health.json').read_text())
    with tempfile.TemporaryDirectory(prefix='zepp-grafana-range-') as tmp:
        root=Path(tmp);root.chmod(0o755)
        data=root/'data';data.mkdir();os.chown(data,472,472)
        provision=root/'provisioning'/'datasources';provision.mkdir(parents=True)
        (provision/'vm.yaml').write_text('apiVersion: 1\ndatasources:\n  - name: VM regression\n    uid: zepp-test\n    type: victoriametrics-metrics-datasource\n    access: proxy\n    url: '+args.vm_url+'\n    jsonData:\n      httpMethod: POST\n')
        try:
            docker('run','-d','--name',name,'--network',args.network,'--user','472',
                   '--label','traefik.enable=false',
                   '-e','GF_SECURITY_ADMIN_USER=regression','-e','GF_SECURITY_ADMIN_PASSWORD='+password,
                   '-e','GF_ANALYTICS_REPORTING_ENABLED=false','-e','GF_ANALYTICS_CHECK_FOR_UPDATES=false',
                   '-e','GF_PLUGINS_PREINSTALL_DISABLED=true',
                   '--mount',f'type=bind,source={data},target=/var/lib/grafana',
                   '--mount',f'type=bind,source={root/"provisioning"},target=/etc/grafana/provisioning,readonly',
                   '--mount',f'type=bind,source={args.plugin_dir.resolve()},target=/var/lib/grafana/plugins/victoriametrics-metrics-datasource,readonly',args.image)
            ip=json.loads(docker('inspect',name))[0]['NetworkSettings']['Networks'][args.network]['IPAddress']
            base=f'http://{ip}:3000';session=requests.Session();session.trust_env=False;session.auth=('regression',password)
            deadline=time.monotonic()+90
            while True:
                try:
                    if session.get(base+'/api/health',timeout=2).ok:break
                except requests.RequestException:pass
                if time.monotonic()>deadline:raise AssertionError('Isolated Grafana did not start')
                time.sleep(.5)
            panels=[p for p in dashboard['panels'] if p['title'].endswith('· 分钟明细')]
            end=1790587845000
            def query(panel,days,legacy=False):
                queries=[]
                for target in panel['targets']:
                    target=dict(target,expr=target['expr'].replace('${account:regex}','personal'),
                                datasource={'uid':'zepp-test','type':'victoriametrics-metrics-datasource'},
                                maxDataPoints=100000 if legacy else panel['maxDataPoints'],intervalMs=60000)
                    queries.append(target)
                response=session.post(base+'/api/ds/query',json={'from':str(end-days*86400000),'to':str(end),'queries':queries},timeout=60)
                body=response.json()
                errors=[x.get('error') for x in body.get('results',{}).values() if x.get('error')]
                if legacy:
                    assert any('too many points' in x for x in errors),(response.status_code,errors)
                    print('Reproduced original 90-day point-limit failure via installed plugin')
                    return
                assert response.ok and not errors,(days,response.status_code,errors)
                count=0
                for result in body['results'].values():
                    for frame in result.get('frames',[]):
                        values=frame.get('data',{}).get('values',[])
                        n=len(values[0]) if values else 0
                        assert n<30000,(days,n)
                        count=max(count,n)
                return count
            query(panels[0],90,legacy=True)
            for days in (1,30,90,365):
                sizes=[query(panel,days) for panel in panels]
                print(f'PASS: {days} days, four panels, max returned points per series {max(sizes)}')
        finally:
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
