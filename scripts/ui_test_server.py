"""Isolated real API for CI browser checks; never starts network sync workers."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from zepp_report.app import create_app

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='zepp-ui-ci-') as directory:
        app=create_app(directory,{'ADMIN_PASSWORD':'isolated-ci-password','COOKIE_SECURE':'false'},start_worker=False)
        uvicorn.run(app,host='127.0.0.1',port=18187,access_log=False)
