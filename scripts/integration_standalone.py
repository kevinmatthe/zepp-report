#!/usr/bin/env python3
"""Exercise the shipped Compose without touching any existing stack or data."""
import sys, tempfile, subprocess, shutil, os, time, json, argparse, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from zepp_report.settings import Settings
from zepp_report.store import Store
from zepp_report.vm_audit import VMAuditor
from zepp_report.sync import SyncService
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Isolated Compose, VM repair and Grafana provisioning smoke test (requires Docker and root for bind ownership)')
parser.add_argument('--image', default='ghcr.io/kevinmatthe/zepp-report:latest')
args=parser.parse_args()
def cmd(*args): return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()
with tempfile.TemporaryDirectory(prefix='zepp-compose-') as td:
 p=Path(td);p.chmod(0o755)
 shutil.copy(root/'compose.yaml',p/'compose.yaml');shutil.copytree(root/'grafana',p/'grafana')
 for f in (p/'grafana').rglob('*'): f.chmod(0o755 if f.is_dir() else 0o644)
 (p/'grafana').chmod(0o755)
 (p/'.env').write_text('ADMIN_PASSWORD=isolated-test-password\nAPP_IMAGE='+args.image+'\n')
 for name,uid in [('data',1000),('vm-data',1000),('grafana-data',472)]:
  d=p/name;d.mkdir();os.chown(d,uid,uid)
 project='zepp-compose-'+uuid.uuid4().hex[:10]; base=['docker','compose','--project-directory',td,'-p',project,'--profile','grafana']
 try:
  print(cmd(*base,'up','-d','--no-build'),flush=True)
  cid=cmd(*base,'ps','-q','zepp-vm');ip=cmd('docker','inspect',cid,'--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
  os.environ['NO_PROXY']=ip;os.environ['no_proxy']=ip
  url='http://'+ip+':8428'
  for _ in range(60):
   try:
    if requests.get(url+'/health',timeout=2).ok: break
   except requests.RequestException: pass
   time.sleep(1)
  else: raise AssertionError('VM unavailable')
  cfg=Settings(p/'audit',{'ADMIN_PASSWORD':'isolated-test-password','VM_IMPORT_URL':url+'/api/v1/import','VM_QUERY_URL':url,'VM_RETENTION_DAYS':'3650','VM_DEDUP_INTERVAL_SECONDS':'.001'})
  db=Store(p/'audit/db');audit=VMAuditor(cfg,db)
  ts=1767225600000;day='2026-01-01'
  db.save(day,'band',{}, {'summary':{'steps':321}},[{'metric':{'__name__':'zepp_steps_daily','account':'personal'},'timestamps':[ts],'values':[321]}])
  db.ack([r['id'] for r in db.pending()]) # simulate successful HTTP acknowledgement without persistence
  with db.connect() as con: con.execute('UPDATE vm_audits SET next_check=0')
  assert audit.tick();assert db.stats()['pending_exports']==1
  SyncService(cfg,db).flush()
  assert db.stats()['pending_exports']==0
  time.sleep(7)
  with db.connect() as con: con.execute('UPDATE vm_audits SET next_check=0')
  assert VMAuditor(cfg,Store(p/'audit/db')).tick()
  assert audit.status()['states']['verified']==1,audit.status()
  print('PASS: separate VM nonroot persistent storage, January missing sample repair and restart readback',flush=True)
  gcid=cmd(*base,'ps','-q','zepp-grafana');gip=cmd('docker','inspect',gcid,'--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}');os.environ['NO_PROXY']+=','+gip
  gurl='http://'+gip+':3000';session=requests.Session();session.trust_env=False
  for _ in range(90):
   try:
    r=session.get(gurl+'/api/datasources/uid/zepp-victoriametrics',auth=('admin','isolated-test-password'),timeout=2)
    if r.ok: break
   except requests.RequestException: pass
   time.sleep(1)
  else: raise AssertionError('Grafana provisioning unavailable: '+cmd(*base,'logs','--tail','15','zepp-grafana'))
  assert r.json()['url']=='http://zepp-vm:8428',r.text
  r=session.get(gurl+'/api/dashboards/uid/zepp-health',auth=('admin','isolated-test-password'));assert r.ok,r.text
  print('PASS: optional Grafana profile installs native plugin and provisions dashboard/datasource',flush=True)
 finally: print(cmd(*base,'down'),flush=True)
