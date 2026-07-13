from time import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

from uvicorn import Config as APIConfig
from uvicorn import Server
from ..config import Parameter, Settings
from ..downloader import Downloader
from ..extract import APIExtractor, HTMLExtractor
from ..interface import Account
from ..link import DetailPage, Examiner
from ..manager import Cache, DownloadRecorder, Manager
from ..module import Database, choose
from ..record import BaseLogger, LoggerManager
from ..request import Detail, User
from ..static import (
    DISCLAIMER_TEXT,
    LICENCE,
    PROJECT_NAME,
    REPOSITORY,
    VERSION_BETA,
    VERSION_MAJOR,
    VERSION_MINOR,
    __VERSION__,
)
from textwrap import dedent
from ..tools import (
    ERROR,
    INFO,
    MASTER,
    WARNING,
    Cleaner,
    ColorConsole,
    Mapping,
    Version,
    suspend,
)
from ..translation import _, switch_language
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from ..model import (
    DetailModel,
    ResponseModel,
    ShortUrl,
    UrlResponse,
)

if TYPE_CHECKING:
    pass


class KS:
    VERSION_MAJOR = VERSION_MAJOR
    VERSION_MINOR = VERSION_MINOR
    VERSION_BETA = VERSION_BETA

    cleaner = Cleaner()

    NAME = PROJECT_NAME
    WIDTH = 50
    LINE = ">" * WIDTH

    DOMAINS: list[str] = [
        "kuaishou.com",
    ]

    def __init__(
        self,
        server_mode: bool = False,
    ):
        self.console = ColorConsole(
            self.VERSION_BETA,
        )
        self.settings_obj = Settings(console=self.console)
        self.settings = self.settings_obj.read()
        self.params = Parameter(
            console=self.console,
            cleaner=self.cleaner,
            **self.settings,
        )
        self.config: dict | None = None
        self.option: dict | None = None
        self.manager = Manager(**self.params.run())
        self.database = Database(self.manager)
        self.mapping = Mapping(self.manager, self.database)
        self.version = Version(self.manager)
        self.examiner = Examiner(self.manager)
        self.detail_html = DetailPage(self.manager)
        self.extractor_api = APIExtractor(self.manager)
        self.extractor_html = HTMLExtractor(self.manager)
        self.recorder = DownloadRecorder(
            self.database, 1, self.console
        )
        self.cache = Cache(self.database, self.console)
        self.logger: BaseLogger = BaseLogger(
            self.manager.root if hasattr(self.manager, 'root') else self.manager.path,
            self.console,
        )
        self.download = Downloader(
            self.manager,
            self.database,
            server_mode,
        )
        self.running = True
        self.__function = None

    async def run(self):
        self.config = await self.database.read_config()
        self.option = await self.database.read_option()
        self.set_language(self.option["Language"])
        self._setup_logger()
        await self.recorder.initialize()
        self.download.recorder = self.recorder
        self.__welcome()
        if await self.disclaimer():
            await self.__main_menu()

    def _setup_logger(self):
        if self.config.get("Logger", 0):
            self.logger = LoggerManager(
                self.manager.root,
                self.console,
            )
            self.logger.run()
            self.logger.info("KS-Downloader 启动")
        else:
            self.logger = BaseLogger(
                self.manager.root,
                self.console,
            )

    async def __main_menu(self):
        while self.running:
            self.__update_menu()
            function = choose(
                _("请选择 KS-Downloader 功能"),
                [i for i, __ in self.__function],
                self.console,
            )
            if function.upper() == "Q":
                self.running = False
            try:
                n = int(function) - 1
            except ValueError:
                break
            if n in range(len(self.__function)):
                await self.__function[n][1]()

    def __update_menu(self):
        tip = {
            0: _("启用"),
            1: _("禁用"),
        }
        self.__function = (
            (_("批量下载快手账号作品"), self.ks_account_interactive),
            (_("批量下载链接作品"), self.__detail_enquire),
            (
                tip[self.config["Record"]] + _("下载记录功能"),
                self.__modify_record,
            ),
            (_("检查程序版本更新"), self.__update_version),
            (_("切换语言"), self._switch_language),
        )

    # ==================== 快手账号批量下载 ====================

    async def ks_account_interactive(self):
        accounts = self.settings.get("ks_accounts", [])
        accounts = [a for a in accounts if a.get("enable", True)]
        if not accounts:
            self.logger.warning(_("settings.json 中没有启用的快手账号！"))
            return

        self.logger.info(
            _("共有 {count} 个快手账号等待下载").format(count=len(accounts))
        )
        count = SimpleNamespace(time=time(), success=0, failed=0)
        for index, account in enumerate(accounts, start=1):
            mark = account.get("mark", "")
            url = account.get("url", "")
            earliest = account.get("earliest", "")
            latest = account.get("latest", "")
            self.logger.info(
                _("处理第 {index}/{total} 个账号: {mark}").format(
                    index=index, total=len(accounts), mark=mark
                )
            )
            try:
                result = await self.deal_ks_account(
                    index, url, mark, earliest, latest
                )
                if result:
                    count.success += 1
                else:
                    count.failed += 1
            except Exception as e:
                import traceback
                self.logger.error(
                    _("处理账号 {mark} 失败: {error}").format(mark=mark, error=e)
                )
                self.logger.error(
                    _("详细错误信息: {trace}").format(
                        trace=traceback.format_exc()
                    )
                )
                count.failed += 1
            if index < len(accounts):
                await suspend(index, self.console, batches=22, rest_time=44)

        elapsed = time() - count.time
        self.logger.info(
            _("处理完成：成功 {success} 个，失败 {failed} 个，耗时 {minutes} 分 {seconds} 秒").format(
                success=count.success,
                failed=count.failed,
                minutes=int(elapsed // 60),
                seconds=int(elapsed % 60),
            )
        )

    async def deal_ks_account(
        self,
        index: int,
        url: str,
        mark: str,
        earliest: str = "",
        latest: str = "",
    ):
        # 1. 提取 userId
        user_ids = await self.examiner.run(url, "user")
        if not user_ids:
            self.logger.warning(
                _("{url} 提取账号 userId 失败").format(url=url)
            )
            return False
        user_id = user_ids[0][1] if isinstance(user_ids[0], tuple) else user_ids[0]

        # 2. 获取作品列表
        account_api = Account(
            self.manager,
            self.settings.get("ks_cookie", self.manager.ks_cookie),
        )
        feeds, temp1, temp2 = await account_api.run(user_id, earliest, latest)
        if not feeds:
            self.logger.warning(
                _("账号 {mark} 没有找到符合条件的作品").format(mark=mark)
            )
            return False

        self.logger.info(
            _("账号 {mark} 共获取 {count} 个作品").format(mark=mark, count=len(feeds))
        )

        # 3. 处理每个作品
        data_list = []
        for feed in feeds:
            photo = feed.get("photo", {})
            if not photo:
                continue
            detail_id = photo.get("id", "")
            if not detail_id:
                continue
            if await self.recorder.has_id(detail_id):
                continue
            # 获取作品详情
            detail_url = f"https://www.kuaishou.com/short-video/{detail_id}"
            html = await self.detail_html.run(detail_url)
            if not html:
                continue
            data = self.extractor_html.run(html, detail_id, True)
            if not data or not data.get("download"):
                continue
            data["mark"] = mark
            data_list.append(data)

        if not data_list:
            self.logger.warning(
                _("账号 {mark} 没有可下载的作品").format(mark=mark)
            )
            return True

        # 4. 下载（使用 manager.folder 作为根目录）
        from pathlib import Path
        root = self.manager.folder
        mark_folder = root.joinpath(mark) if mark else root.joinpath(user_id)
        mark_folder.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            _("开始下载 {count} 个作品到 {folder}").format(
                count=len(data_list), folder=mark_folder
            )
        )
        for data in data_list:
            await self._download_single(data, mark_folder)

        # 5. 更新缓存
        await self.cache.update_cache(user_id, mark, mark)
        return True

    async def _download_single(self, data: dict, folder):
        from shutil import move
        downloads = data.get("download", [])
        if isinstance(downloads, str):
            downloads = [downloads]
        for idx, url in enumerate(downloads):
            if not url:
                continue
            detail_id = data.get("detailID", "")
            if await self.recorder.has_id(detail_id):
                continue
            name = data.get("caption", detail_id)
            if not isinstance(name, str):
                name = str(name) if name is not None else detail_id
            name = self.cleaner.filter_name(name) or detail_id
            suffix = "mp4" if data.get("photoType") == _("视频") else "webp"
            file_path = folder.joinpath(f"{name}_{idx}.{suffix}")
            if file_path.exists():
                self.logger.info(_("文件已存在，跳过: {path}").format(path=file_path.name))
                continue
            temp_path = self.manager.temp.joinpath(f"{file_path.name}.tmp")
            self.logger.info(_("下载: {path}").format(path=file_path.name))
            try:
                async with self.manager.client.stream(
                    "GET", url, headers=self.manager.pc_download_headers
                ) as response:
                    response.raise_for_status()
                    with open(temp_path, "wb") as f:
                        async for chunk in response.aiter_bytes(self.manager.chunk):
                            f.write(chunk)
                move(temp_path.resolve(), file_path.resolve())
                await self.recorder.update_id(detail_id)
                self.logger.info(_("下载完成: {path}").format(path=file_path.name))
            except Exception as e:
                self.logger.error(
                    _("下载失败 {url}: {error}").format(url=url, error=e)
                )
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    # ==================== 单作品下载 ====================

    async def __detail_enquire(self):
        while self.running:
            text = self.console.input(_("请输入快手作品链接："))
            if not text:
                break
            if text.upper() == "Q":
                self.running = False
                break
            await self.detail(text)

    # ==================== 设置管理 ====================

    async def _switch_language(
        self,
    ):
        if self.option["Language"] == "zh_CN":
            language = "en_US"
        elif self.option["Language"] == "en_US":
            language = "zh_CN"
        else:
            raise TypeError(self.option["Language"])
        await self._update_language(language)

    async def _update_language(self, language: str) -> None:
        self.option["Language"] = language
        await self.database.update_option_data("Language", language)
        self.set_language(language)

    async def __update_version(self):
        if target := await self.version.get_target_version():
            state = self.version.compare_versions(
                f"{self.VERSION_MAJOR}.{self.VERSION_MINOR}",
                target,
                self.VERSION_BETA,
            )
            self.console.print(
                self.version.STATUS_CODE[state], style=INFO if state == 1 else WARNING
            )
        else:
            self.console.print(_("检测新版本失败"), style=ERROR)

    async def __modify_record(self):
        await self.__update_config("Record", 0 if self.config["Record"] else 1)
        self.database.record = self.config["Record"]
        self.recorder.switch = self.config["Record"]
        if self.config["Record"]:
            await self.recorder.initialize()
        self.console.print(
            _("修改设置成功！"),
            style=INFO,
        )

    async def __update_config(self, key: str, value: int):
        self.config[key] = value
        await self.database.update_config_data(key, value)

    # ==================== 单作品下载（保留原逻辑）====================

    async def detail(
        self,
        detail: str,
        download: bool = True,
    ) -> None:
        urls = await self.examiner.run(
            detail,
        )
        if not urls:
            message = _("提取作品链接失败")
            self.console.warning(message)
            return message
        for url in urls:
            if isinstance(
                m := await self.detail_one(
                    url,
                    download,
                ),
                str,
            ):
                self.console.warning(m)
        return None

    async def detail_one(
        self,
        url: str,
        download: bool = False,
        proxy: str = "",
        cookie: str = "",
    ) -> dict | str:
        web, user_id, detail_id = self.examiner.extract_params(
            url,
        )
        if not detail_id:
            message = _("URL 解析失败：{url}").format(url=url)
            self.console.warning(message)
            return message
        data = await self.__handle_detail_html(
            detail_id,
            url,
            web,
            proxy,
            cookie,
        )
        if not data:
            return _("获取作品数据失败")
        await self.update_author_nickname(
            data,
        )
        if download:
            await self.__download_file(
                [data],
            )
        await self.__save_data([data], "Download")
        return data

    async def update_author_nickname(
        self,
        data: dict,
    ):
        if a := self.cleaner.filter_name(
            self.manager.mapping_data.get(i := data.get("authorID", ""), "")
        ):
            data["name"] = a
        else:
            data["name"] = self.manager.filter_name(data.get("name", "")) or i
        await self.mapping.update_cache(
            i,
            data.get("name", ""),
        )

    async def __handle_detail_html(
        self,
        detail_id: str,
        url: str,
        web: bool,
        proxy: str = "",
        cookie: str = "",
    ) -> dict | None:
        if html := await self.detail_html.run(url, proxy, cookie):
            return self.extractor_html.run(
                html,
                detail_id,
                web,
            )
        return None

    async def __save_data(
        self, data: list[dict], name: str, type_="detail", format_="SQLite"
    ) -> None:
        pass

    async def __download_file(
        self,
        data: list[dict],
        type_="detail",
    ):
        await self.download.run(
            data,
            type_,
        )

    # ==================== 用户相关 ====================

    async def user(
        self,
        text: str,
        download: bool = True,
    ) -> None:
        items: list[tuple[str, str]] = await self.examiner.run(
            text,
            "user",
        )
        if not any(items):
            message = _("提取账号链接失败")
            self.console.warning(message)
            return message
        for url, id_ in items:
            if isinstance(
                m := await self.user_one(
                    url,
                    id_,
                    download=download,
                ),
                str,
            ):
                self.console.warning(m)
        return None

    async def user_one(
        self,
        user_url: str,
        user_id: str,
        cursor: str = "",
        download: bool = False,
        proxy: str = "",
        cookie: str = "",
    ):
        response = await User(
            self.manager,
            cookie,
            proxy,
            user_id,
            cursor,
        ).run()
        self.logger.info(str(response))

    # ==================== 启动 / 免责 ====================

    def __welcome(self):
        self.console.print(self.LINE, style=MASTER)
        self.console.print("\n")
        self.console.print(self.NAME.center(self.WIDTH), style=MASTER)
        self.console.print("\n")
        self.console.print(self.LINE, style=MASTER)
        self.console.print()
        self.console.print(_("项目地址：{repo}").format(repo=REPOSITORY), style=MASTER)
        self.console.print(
            _("开源协议：{licence}").format(licence=LICENCE), style=MASTER
        )
        self.console.print()

    async def disclaimer(self):
        if self.config["Disclaimer"]:
            return True
        await self.__init_language()
        self.console.print(
            _(DISCLAIMER_TEXT),
            style=MASTER,
        )
        if self.console.input(
            _("是否已仔细阅读上述免责声明(YES/NO): ")
        ).upper() not in (
            "YES",
            "Y",
        ):
            return False
        await self.database.update_config_data("Disclaimer", 1)
        self.console.print()
        return True

    async def __init_language(self):
        languages = (
            (
                "简体中文",
                "zh_CN",
            ),
            (
                "English",
                "en_US",
            ),
        )
        language = choose(
            "请选择语言(Please Select Language)",
            [i[0] for i in languages],
            self.console,
        )
        try:
            language = languages[int(language) - 1][1]
            await self._update_language(language)
        except ValueError:
            await self.__init_language()

    # ==================== 生命周期 ====================

    async def close(self):
        if hasattr(self.logger, 'log') and self.logger.log:
            self.logger.info(_("正在关闭程序"))
        await self.recorder.close()
        await self.manager.close()

    async def __aenter__(self):
        await self.database.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.database.__aexit__(exc_type, exc_val, exc_tb)
        await self.close()

    @staticmethod
    def set_language(language: str) -> None:
        switch_language(language)

    # ==================== API Server ====================

    async def run_api_server(
        self,
        host="0.0.0.0",
        port=5556,
        log_level="info",
    ):
        api = FastAPI(
            debug=self.VERSION_BETA,
            title="KS-Downloader",
            version=__VERSION__,
        )
        self.setup_routes(api)
        config = APIConfig(
            api,
            host=host,
            port=port,
            log_level=log_level,
        )
        server = Server(config)
        await server.serve()

    def setup_routes(
        self,
        server: FastAPI,
    ):
        @server.get(
            "/",
            summary=_("跳转至项目 GitHub 仓库"),
            description=_("重定向至项目 GitHub 仓库主页"),
            tags=["Project"],
        )
        async def index():
            return RedirectResponse(url=REPOSITORY)

        @server.post(
            "/share",
            summary=_("获取作品分享链接的重定向链接"),
            description=_(
                dedent(
                    """
                    **参数**:
                            
                    - **text**: 包含作品链接的文本；必需参数
                    - **proxy**: 请求数据时使用的代理；可选参数
                    """
                )
            ),
            tags=["API"],
            response_model=UrlResponse,
        )
        async def share(extract: ShortUrl):
            if urls := await self.examiner.run(
                extract.text,
                type_="",
                proxy=extract.proxy,
            ):
                return UrlResponse(
                    message=_("请求重定向链接成功！"),
                    params=extract,
                    urls=urls,
                )
            return UrlResponse(
                message=_("请求重定向链接失败！"),
                params=extract,
                urls=None,
            )

        @server.post(
            "/detail/",
            summary=_("获取作品数据"),
            description=_(
                dedent(
                    """
                    **参数**:
                        
                    - **text**: 作品链接，自动提取；必需参数
                    - **cookie**: 请求数据时使用的 Cookie；可选参数
                    - **proxy**: 请求数据时使用的代理；可选参数
                    """
                )
            ),
            tags=["API"],
            response_model=ResponseModel,
        )
        async def detail(extract: DetailModel):
            urls = await self.examiner.run(extract.text, proxy=extract.proxy)
            if not urls:
                message = _("提取作品链接失败")
                data = None
                self.console.warning(message)
            else:
                if isinstance(
                    data := await self.detail_one(
                        urls[0], proxy=extract.proxy, cookie=extract.cookie
                    ),
                    dict,
                ):
                    message = _("获取作品数据成功")
                else:
                    message = data
                    data = None
            return ResponseModel(message=message, params=extract, data=data)