from asyncio import Lock
from re import compile
from time import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ..module import Database
    from ..tools import ColorConsole

__all__ = ["DownloadRecorder"]


class DownloadRecorder:
    detail = compile(r"\w+")

    def __init__(self, database: "Database", switch: bool, console: "ColorConsole"):
        self.switch = switch
        self.console = console
        self.database = database
        # 内存缓存层
        self._cache: set = set()
        self._pending: set = set()
        self._flush_threshold = 15
        self._last_flush_time = 0.0
        self._initialized = False
        self._flush_lock = Lock()

    async def initialize(self):
        """启动时从 SQLite 全量加载已下载 ID 到内存缓存"""
        if not self.switch:
            self._initialized = True
            return
        self._cache = await self.database.load_all_download_ids()
        self._last_flush_time = time()
        self._initialized = True

    async def has_id(self, id_: str) -> bool:
        if not self.switch or not id_:
            return False
        return id_ in self._cache

    async def update_id(self, id_: str):
        if not self.switch or not id_:
            return
        self._cache.add(id_)
        self._pending.add(id_)
        # 双重触发：累积 ≥ 20 条 或 距上次 flush > 60 秒
        if len(self._pending) >= self._flush_threshold or (
            time() - self._last_flush_time
        ) > 60:
            await self._flush()

    async def _flush(self):
        """批量写入 pending 中的 ID 到 SQLite"""
        async with self._flush_lock:
            if not self._pending:
                return
            snapshot = self._pending.copy()
            self._pending.clear()
            self._last_flush_time = time()
        await self.database.batch_write_download_data(snapshot)

    async def flush(self):
        """公开的刷盘方法，关闭时强制调用"""
        await self._flush()

    async def delete_id(self, id_: str) -> None:
        if not self.switch or not id_:
            return
        self._cache.discard(id_)
        self._pending.discard(id_)
        await self.database.delete_download_data(id_)

    async def delete_ids(self, ids: str) -> None:
        if ids.upper() == "ALL":
            self._cache.clear()
            self._pending.clear()
            await self.database.delete_all_download_data()
        else:
            ids = self.__extract_ids(ids)
            for id_ in ids:
                self._cache.discard(id_)
                self._pending.discard(id_)
            await self.database.delete_download_data(ids)

    def __extract_ids(self, ids: str) -> list[str]:
        ids = ids.split()
        result = []
        for i in ids:
            if id_ := self.detail.search(i):
                result.append(id_.group())
        return result

    async def close(self):
        """程序关闭时强制刷盘"""
        await self._flush()