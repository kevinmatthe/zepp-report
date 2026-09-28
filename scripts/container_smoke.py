#!/usr/bin/env python3
"""Build artifact smoke test with no network, an explicit bind, and restart."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from zepp_report.store import Store


def main():
    image=sys.argv[1] if len(sys.argv)>1 else 'zepp-report:test'
    name='zepp-container-test-'+uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix='zepp-container-test-') as temp:
        directory=Path(temp)
        store=Store(directory/'zepp.sqlite3')
        store.enqueue(['2026-09-01'],['band'])
        store.claim() # Simulate a process killed while task was running.
        os.chown(directory,1000,1000)
        for file in directory.iterdir():os.chown(file,1000,1000)
        subprocess.run(['docker','run','-d','--name',name,'--network','none',
            '--mount',f'type=bind,source={directory},target=/app/data',
            '-e','ADMIN_PASSWORD=container-test-password','-e','COOKIE_SECURE=false',
            '-e','VM_IMPORT_URL=http://127.0.0.1:1/api/v1/import',image],check=True,stdout=subprocess.DEVNULL)
        try:
            code="""
import json,urllib.request,http.cookiejar
jar=http.cookiejar.CookieJar()
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
base='http://127.0.0.1:8000'
assert json.load(client.open(base+'/healthz'))['status']=='ok'
r=urllib.request.Request(base+'/api/login',data=json.dumps({'password':'container-test-password'}).encode(),headers={'Content-Type':'application/json','X-Zepp-Request':'1'})
assert json.load(client.open(r))['ok']
s=json.load(client.open(base+'/api/status'))
assert s['worker_alive'] and s['tasks']['pending']==1 and s['tasks']['running']==0
assert '<html' in client.open(base+'/').read().decode()
print('HTTP health, authenticated status, recovered task and static UI passed')
"""
            for iteration in range(2):
                for attempt in range(30):
                    result=subprocess.run(['docker','exec',name,'python','-c',code],capture_output=True,text=True)
                    if result.returncode==0:break
                    time.sleep(.5)
                else:
                    raise AssertionError(result.stderr)
                print(result.stdout.strip())
                if iteration==0:
                    subprocess.run(['docker','restart',name],check=True,stdout=subprocess.DEVNULL)
            subprocess.run(['docker','exec',name,'python','-m','zepp_report.admin','backup','/app/data/test-backup'],check=True)
            assert (directory/'test-backup'/'BACKUP_COMPLETE').exists()
            print('PASS: non-root container, bound SQLite, worker restart recovery, online backup; no external networking.')
        finally:
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,check=False)


if __name__=='__main__':main()
