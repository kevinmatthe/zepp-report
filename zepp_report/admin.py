"""Offline/online archive maintenance: python -m zepp_report.admin backup PATH."""
import argparse
import json
import os
from pathlib import Path
import sqlite3


def backup(source,destination):
    source,destination=Path(source),Path(destination)
    database=source/'zepp.sqlite3'
    if not database.is_file():
        raise ValueError('找不到源数据库')
    destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    target=destination/'zepp.sqlite3'
    # SQLite backup API includes WAL transactions and produces a consistent snapshot.
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as origin:
        with sqlite3.connect(target) as replica:
            origin.backup(replica,pages=256)
            if replica.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('数据库备份完整性检查失败')
    os.chmod(target,0o600)
    config=source/'settings.json'
    if config.is_file():
        content=config.read_bytes()
        json.loads(content)
        fd=os.open(destination/'settings.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    (destination/'BACKUP_COMPLETE').write_text('SQLite integrity_check: ok\n')


def main():
    parser=argparse.ArgumentParser(description='Zepp Report archive maintenance')
    parser.add_argument('--data-dir',default=os.environ.get('DATA_DIR','./data'))
    sub=parser.add_subparsers(dest='command',required=True)
    cmd=sub.add_parser('backup',help='Create a consistent SQLite backup in a new directory')
    cmd.add_argument('destination')
    args=parser.parse_args()
    backup(args.data_dir,args.destination)
    print('备份完成（包含健康数据及本地凭据，请妥善保存）')


if __name__=='__main__':main()
