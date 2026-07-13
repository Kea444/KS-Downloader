from asyncio import sleep
from typing import TYPE_CHECKING

from ..translation import _

if TYPE_CHECKING:
    from .console import ColorConsole


async def suspend(
    count: int,
    console: "ColorConsole",
    batches: int = 22,
    rest_time: int = 44,
) -> None:
    """
    每处理指定数量的数据后暂停，避免请求频率过高导致 IP/账号被风控
    仅对批量下载模式生效。此处的一个数据代表一个账号。
    """
    if not count % batches:
        console.print(
            _(
                "程序连续处理了 {batches} 个账号，为了避免请求频率过高导致账号或 IP 被风控，"
                "程序已经暂停运行，将在 {rest_time} 秒后恢复运行！"
            ).format(batches=batches, rest_time=rest_time),
        )
        await sleep(rest_time)