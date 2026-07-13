from typing import TYPE_CHECKING
from asyncio import CancelledError
from contextlib import suppress
from aiosqlite import Row, connect
from shutil import move
from ..static import PROJECT_ROOT

if TYPE_CHECKING:
    from ..manager import Manager


class Database:
    record = 1
    __FILE = "KSdata.db"

    def __init__(
        self,
        manager: "Manager",
    ):
        self.file = PROJECT_ROOT.joinpath(self.__FILE)
        self.compatible()
        self.database = None
        self.cursor = None

    async def __connect_database(self):
        self.database = await connect(self.file)
        self.database.row_factory = Row
        self.cursor = await self.database.cursor()
        await self.__create_table()
        await self.__write_default_config()
        await self.__write_default_option()
        await self.database.commit()

    async def __create_table(self):
        await self.database.execute(
            """CREATE TABLE IF NOT EXISTS config_data (
            NAME TEXT PRIMARY KEY,
            VALUE INTEGER NOT NULL CHECK(VALUE IN (0, 1))
            );"""
        )
        await self.database.execute(
            "CREATE TABLE IF NOT EXISTS download_data (ID TEXT PRIMARY KEY);"
        )
        await self.database.execute("""CREATE TABLE IF NOT EXISTS mapping_data (
        ID TEXT PRIMARY KEY,
        NAME TEXT NOT NULL,
        MARK TEXT NOT NULL
        );""")
        await self.database.execute("""CREATE TABLE IF NOT EXISTS option_data (
        NAME TEXT PRIMARY KEY,
        VALUE TEXT NOT NULL
        );""")

    async def __write_default_config(self):
        await self.database.execute("""INSERT OR IGNORE INTO config_data (NAME, VALUE)
                            VALUES ('Record', 1),
                            ('Logger', 0),
                            ('Disclaimer', 0);""")

    async def __write_default_option(self):
        await self.database.execute("""INSERT OR IGNORE INTO option_data (NAME, VALUE)
                            VALUES ('Language', 'zh_CN');""")

    async def read_config_data(self):
        await self.cursor.execute("SELECT * FROM config_data")
        return await self.cursor.fetchall()

    async def read_option_data(self):
        await self.cursor.execute("SELECT * FROM option_data")
        return await self.cursor.fetchall()

    async def update_config_data(self, name: str, value: int):
        await self.database.execute(
            "REPLACE INTO config_data (NAME, VALUE) VALUES (?,?)", (name, value)
        )
        await self.database.commit()

    async def update_option_data(self, name: str, value: str):
        await self.database.execute(
            "REPLACE INTO option_data (NAME, VALUE) VALUES (?,?)", (name, value)
        )
        await self.database.commit()

    async def update_mapping_data(self, id_: str, name: str, mark: str):
        await self.database.execute(
            "REPLACE INTO mapping_data (ID, NAME, MARK) VALUES (?,?,?)",
            (id_, name, mark),
        )
        await self.database.commit()

    async def read_mapping_data(self, id_: str):
        await self.cursor.execute(
            "SELECT NAME, MARK FROM mapping_data WHERE ID=?", (id_,)
        )
        return await self.cursor.fetchone()

    async def has_download_data(self, id_: str) -> bool:
        if not self.record:
            return False
        await self.cursor.execute("SELECT ID FROM download_data WHERE ID=?", (id_,))
        return bool(await self.cursor.fetchone())

    async def write_download_data(self, id_: str):
        if self.record:
            await self.database.execute(
                "INSERT OR IGNORE INTO download_data (ID) VALUES (?);", (id_,)
            )
            await self.database.commit()

    async def batch_write_download_data(self, ids: set):
        """批量写入已下载 ID，单次 commit，高效减少锁竞争"""
        if not ids:
            return
        await self.database.executemany(
            "INSERT OR IGNORE INTO download_data (ID) VALUES (?);",
            [(i,) for i in ids],
        )
        await self.database.commit()

    async def load_all_download_ids(self) -> set:
        """一次性加载全部已下载 ID 到内存 set，用于构建缓存"""
        await self.cursor.execute("SELECT ID FROM download_data")
        return {row[0] for row in await self.cursor.fetchall()}

    async def delete_download_data(self, ids):
        if not ids:
            return
        if isinstance(ids, str):
            ids = [ids]
        for id_ in ids:
            await self.database.execute(
                "DELETE FROM download_data WHERE ID=?", (id_,)
            )
        await self.database.commit()

    async def delete_all_download_data(self):
        await self.database.execute("DELETE FROM download_data")
        await self.database.commit()

    async def read_config(
        self,
    ) -> dict:
        config = await self.read_config_data()
        config = self._format_config(config)
        self.record = config["Record"]
        return config

    async def read_option(
        self,
    ) -> dict:
        option = await self.read_option_data()
        option = self._format_config(option)
        return option

    @staticmethod
    def _format_config(config: list) -> dict:
        return {i["NAME"]: i["VALUE"] for i in config}

    async def __aenter__(self):
        await self.__connect_database()
        return self

    async def close(self):
        with suppress(CancelledError):
            await self.cursor.close()
        await self.database.close()

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    def compatible(self):
        if (
            old := PROJECT_ROOT.joinpath("KS-Downloader.db")
        ).exists() and not self.file.exists():
            move(old, self.file)
        if (
            old := PROJECT_ROOT.parent.joinpath(self.__FILE)
        ).exists() and not self.file.exists():
            move(old, self.file)