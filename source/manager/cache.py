from pathlib import Path
from typing import TYPE_CHECKING

from ..translation import _

if TYPE_CHECKING:
    from ..module import Database
    from ..tools import ColorConsole


class Cache:
    def __init__(
        self,
        database: "Database",
        console: "ColorConsole",
    ):
        self.console = console
        self.database = database

    async def update_cache(
        self,
        id_: str,
        name: str,
        mark: str,
    ):
        if d := await self.has_cache(id_):
            self._check_file(id_, name, mark, d)
        data = (id_, name, mark)
        await self.database.update_mapping_data(*data)

    async def has_cache(self, id_: str) -> dict | None:
        return await self.database.read_mapping_data(id_)

    def _check_file(
        self,
        id_: str,
        name: str,
        mark: str,
        data: dict,
    ):
        pass

    def __rename(
        self,
        old_: Path,
        new_: Path,
        type_=_("文件"),
    ) -> bool:
        try:
            old_.rename(new_)
            return True
        except (PermissionError, FileExistsError, OSError) as e:
            self.console.error(
                _("处理{type} {old}时发生错误: {error}").format(
                    type=type_, old=old_, error=e
                ),
            )
            return False