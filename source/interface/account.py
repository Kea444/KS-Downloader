from asyncio import sleep
from random import uniform
from typing import TYPE_CHECKING

from ..tools import capture_error_request, retry_request, wait
from ..translation import _

if TYPE_CHECKING:
    from ..manager import Manager


class Account:
    def __init__(
        self,
        manager: "Manager",
        cookie: str = "",
        proxy: str = "",
    ):
        self.client = manager.client
        self.headers = manager.pc_data_headers.copy()
        self.console = manager.console
        self.retry = manager.max_retry
        self.max_workers = manager.max_workers
        self.proxy = proxy
        if cookie:
            self.headers["Cookie"] = cookie

    async def run(
        self,
        user_id: str,
        earliest: str = "",
        latest: str = "",
        pages: int = None,
    ) -> tuple[list[dict], str, str]:
        account = _AccountCollector(
            self,
            user_id,
            earliest,
            latest,
            pages,
        )
        return await account.run()


class _AccountCollector:
    DOMAIN = "https://www.kuaishou.com"
    API = "/rest/v/profile/feed"

    def __init__(
        self,
        parent: Account,
        user_id: str,
        earliest: str,
        latest: str,
        pages: int,
    ):
        self.parent = parent
        self.user_id = user_id
        self.earliest = earliest
        self.latest = latest
        self.pages = pages
        self.cursor = ""
        self.items: list[dict] = []
        self.finished = False
        self._page_count = 0
        # 装饰器需要这两个属性
        self.console = parent.console
        self.retry = parent.retry

    async def run(self) -> tuple[list[dict], str, str]:
        while not self.finished:
            await self._request_page()
        return self.items, self.earliest, self.latest

    async def _request_page(self):
        data = await self._post_data(
            f"{self.DOMAIN}{self.API}",
            {
                "user_id": self.user_id,
                "pcursor": self.cursor,
                "page": "profile",
            },
        )
        if not data:
            self.finished = True
            return
        feeds = data.get("feeds", [])
        if not feeds:
            self.finished = True
            return
        self.items.extend(feeds)
        self._page_count += 1
        self.cursor = data.get("pcursor", "")
        if not self.cursor:
            self.finished = True
        if self.pages and self._page_count >= self.pages:
            self.finished = True

    @retry_request
    @capture_error_request
    async def _post_data(self, url: str, data: dict) -> dict | None:
        jsondata = data
        response = await self.parent.client.post(
            url,
            headers=self.parent.headers,
            json=jsondata,
        )
        await wait()
        if response.status_code != 200:
            self.console.warning(
                _("API 返回非 200 状态码: {code}，URL: {url}").format(
                    code=response.status_code, url=url
                )
            )
            # 输出响应体前 300 字符帮助诊断
            body_preview = response.text[:300]
            if body_preview:
                self.console.warning(
                    _("响应内容预览: {body}").format(body=body_preview)
                )
        response.raise_for_status()
        # 随机延迟 1-3 秒，降低请求频率
        await sleep(uniform(1, 3))
        return response.json()
