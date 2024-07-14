import logging
import sqlite3
import pathlib

LOGGER = logging.getLogger(__name__)

def dict_factory(cursor, row):
    LOGGER = logging.getLogger(__name__ + ".dict_factory")
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class Database:
    def __init__(self, imei):
        LOGGER = logging.getLogger(__name__ + ".Database--init")
        self.imei = imei
        pathlib.Path('database').mkdir(parents=True, exist_ok=True)
        with open(pathlib.Path('sql' / 'create_points.sql'), 'r', encoding='utf') as f:
            sql = f.read()
        self.execute(sql)


    def execute(self, sql, data=None):
        LOGGER = logging.getLogger(__name__ + ".Database--execute")
        conn = sqlite3.connect(pathlib.Path('database' / f'{self.imei}.db'))
        conn.row_factory = dict_factory
        cur = self.conn.cursor()

        with open(pathlib.Path('sql' / 'create_points.sql'), 'r', encoding='utf') as f:
            sql = f.read()
        cur.execute(sql, data=data)

        # Сохраняем изменения и закрываем соединение
        conn.commit()
        conn.close()


    def add_points(self):
        LOGGER = logging.getLogger(__name__ + ".Database--add_points")
        pass