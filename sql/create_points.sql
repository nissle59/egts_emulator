CREATE TABLE IF NOT EXISTS points (
        pid INTEGER PRIMARY KEY,
        cid INTEGER NOT NULL,
        sid INTEGER NOT NULL,
        lat REAL NOT NULL,
        long REAL NOT NULL,
        seg_time REAL NOT NULL DEFAULT 0,
        seg_len REAL NOT NULL DEFAULT 0,
        passed INTEGER NOT NULL DEFAULT 0
    )