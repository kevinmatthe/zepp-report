"""Additive, repeatable analytics schema; original archives/outbox remain authoritative."""

ALGORITHM_VERSION = 3


def migrate(con):
    con.executescript('''
        CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS analytics_jobs (
            day TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending', error TEXT,
            retry_at REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS analytics_days (
            day TEXT PRIMARY KEY, revision TEXT NOT NULL, version INTEGER NOT NULL,
            timezone TEXT NOT NULL, data TEXT NOT NULL, profiles TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analytics_activities (
            day TEXT NOT NULL, position INTEGER NOT NULL, source TEXT NOT NULL,
            type TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(day,position));
        CREATE INDEX IF NOT EXISTS analytics_activity_filter ON analytics_activities(source,type,day);
        CREATE INDEX IF NOT EXISTS samples_day_kind ON samples(day,kind);
        CREATE TRIGGER IF NOT EXISTS analytics_record_insert AFTER INSERT ON records
        BEGIN
            INSERT INTO analytics_jobs(day) VALUES(NEW.day)
            ON CONFLICT(day) DO UPDATE SET generation=generation+1,status='pending',error=NULL,retry_at=0;
        END;
        CREATE TRIGGER IF NOT EXISTS analytics_record_update AFTER UPDATE ON records
        WHEN OLD.data != NEW.data OR OLD.raw != NEW.raw
        BEGIN
            INSERT INTO analytics_jobs(day) VALUES(NEW.day)
            ON CONFLICT(day) DO UPDATE SET generation=generation+1,status='pending',error=NULL,retry_at=0;
        END;
        INSERT OR IGNORE INTO analytics_jobs(day) SELECT DISTINCT day FROM records;
        INSERT OR IGNORE INTO schema_migrations VALUES(1);
        INSERT OR IGNORE INTO tasks(day,kind,status,updated_at)
            SELECT day,'workouts','pending',strftime('%s','now') FROM tasks
            WHERE kind='band' AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=2);
        INSERT OR IGNORE INTO schema_migrations VALUES(2);
        CREATE TABLE IF NOT EXISTS metric_backfill (
            day TEXT,kind TEXT,done INTEGER NOT NULL DEFAULT 0,
            retry_at REAL NOT NULL DEFAULT 0,error TEXT,PRIMARY KEY(day,kind));
        INSERT OR IGNORE INTO metric_backfill(day,kind)
            SELECT day,kind FROM records WHERE kind IN ('band','workouts')
            AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=3);
        INSERT OR IGNORE INTO schema_migrations VALUES(3);
        INSERT OR IGNORE INTO tasks(day,kind,status,updated_at)
            SELECT day,'spo2','pending',strftime('%s','now') FROM tasks
            WHERE kind='band' AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=4);
        UPDATE metric_backfill SET done=0,retry_at=0,error=NULL WHERE kind='band'
            AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=4);
        INSERT OR IGNORE INTO schema_migrations VALUES(4);
    ''')
