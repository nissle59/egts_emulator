CREATE TABLE IF NOT EXISTS segments (
        sid INTEGER PRIMARY KEY,
        seg_time REAL NOT NULL DEFAULT 0,
        seg_len REAL NOT NULL DEFAULT 0
    )