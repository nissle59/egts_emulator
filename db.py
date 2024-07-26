import logging
from dataclasses import dataclass

import asyncpg
from typing import List, Dict, Any, Union, Optional
from config import DSN, DSN_DEBUG

LOGGER = logging.getLogger(__name__)


class ConnectionDBError(Exception):
    ...


class DBNotConnected(Exception):
    ...


@dataclass
class AsyncPGWrapper:
    conn: Optional[asyncpg.Connection] = None

    def __init__(self, dsn: str):
        self.dsn = dsn

    async def _connect(self):
        if self.conn is not None:
            return True
        try:
            self.conn = await asyncpg.connect(dsn=self.dsn)
        except Exception as e:
            return e
        return True

    async def _disconnect(self):
        if self.conn is None:
            return True
        await self.conn.close(timeout=20)

    async def __aenter__(self):
        res = await self._connect()
        if res is True:
            return self
        raise ConnectionDBError(res)

    async def __aexit__(self, *args):
        await self._disconnect()

    async def fetch(self, query: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        if self.conn is None:
            raise DBNotConnected('Нет подключения к БД! Используйте в блоке async with!')
        try:
            result = await self.conn.fetch(query, *self._prepare_params(params))
        except Exception as e:
            LOGGER.error(f'***\nОшибка при запросе к БД: {e}\n{query}\n***', exc_info=True)
            return None
        return [dict(record) for record in result]

    async def fetchone(self, query: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if self.conn is None:
            raise DBNotConnected('Нет подключения к БД! Используйте в блоке async with!')
        try:
            result = await self.conn.fetchrow(query, *self._prepare_params(params))
        except Exception as e:
            LOGGER.error(f'***\nОшибка при запросе к БД: {e}\n{query}\n***', exc_info=True)
            return None
        return dict(result) if result else None

    async def execute(self, query: str, params: Dict[str, Any] = None):
        if self.conn is None:
            raise DBNotConnected('Нет подключения к БД! Используйте в блоке async with!')
        try:
            result = await self.conn.execute(query, *self._prepare_params(params))
        except Exception as e:
            LOGGER.error(f'***\nОшибка при запросе к БД: {e}\n{query}\n***', exc_info=True)
            return None
        return result

    def _prepare_params(self, params: Dict[str, Any]) -> List[Any]:
        if not params:
            return []
        # Преобразуем словарь параметров в формат, подходящий для asyncpg
        return [params.get(f'@{i + 1}') for i in range(len(params))]


DB = AsyncPGWrapper(DSN)
DB_DEBUG = AsyncPGWrapper(DSN_DEBUG)


async def get():
    async with AsyncPGWrapper(DSN_DEBUG) as db:
        # Пример получения нескольких записей
        records = await db.fetch(
            'SELECT * FROM tg.history WHERE path = %(path)s and filename = %(filename)s order by asctime desc limit 50',
            {'path': 'Сервис.ЕГТС.Генератор', 'filename': 'service_threaded.py'})
        print(records)
