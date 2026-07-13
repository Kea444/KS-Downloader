from json import load as json_load
from platform import system
import sys
from shutil import move
from yaml import safe_load

from ..static import PROJECT_ROOT, VOLUME_ROOT
from ..variable import PC_USERAGENT, RETRY, TIMEOUT


class Settings:
    encode = "UTF-8-SIG" if system() == "Windows" else "UTF-8"

    def __init__(self, console=None):
        self.console = console
        self.file = self._find_settings_file()
        self.data = {}

    @staticmethod
    def _find_settings_file():
        from pathlib import Path
        import sys
        if getattr(sys, 'frozen', False):
            meipass = Path(sys._MEIPASS)
            candidate = meipass / "settings.json"
            if candidate.exists():
                return candidate
        candidate = PROJECT_ROOT.joinpath("settings.json")
        if candidate.exists():
            return candidate
        return PROJECT_ROOT.joinpath("settings.json")

    def read(self) -> dict:
        self.compatible()
        if self.file.exists():
            try:
                with self.file.open("r", encoding=self.encode) as f:
                    self.data = self._check(json_load(f))
            except Exception:
                self.data = self._create()
        else:
            self.data = self._create()
        return self.data

    def _create(self) -> dict:
        """创建默认配置文件，并打印命令行指引"""
        data = self._default()
        self.update(data)
        if self.console:
            self.console.print()
            self.console.print("=" * 50)
            self.console.print("  已创建默认配置文件：settings.json")
            self.console.print("  请编辑该文件，配置以下内容：")
            self.console.print("=" * 50)
            self.console.print()
            self.console.print("  📌 必填项：")
            self.console.print("    1. ks_cookie：快手网页版 Cookie")
            self.console.print("       (F12 → 网络 → 请求头中复制)")
            self.console.print("       ⚠️  不填 Cookie 可能导致下载失败")
            self.console.print()
            self.console.print("  📌 添加快手作者（在 ks_accounts 数组中添加对象）：")
            self.console.print('    {')
            self.console.print('      "mark":     "作者备注名（自定义，方便识别）",')
            self.console.print('      "url":      "https://www.kuaishou.com/profile/3x...",')
            self.console.print('      "earliest": "",    ← 可选，最早发布时间')
            self.console.print('      "latest":   "",    ← 可选，最晚发布时间')
            self.console.print('      "enable":   true   ← true=下载 false=跳过')
            self.console.print('    }')
            self.console.print()
            self.console.print("  📌 URL 支持格式：")
            self.console.print("    · 作者主页：https://www.kuaishou.com/profile/3x...")
            self.console.print("    · 分享短链：https://v.kuaishou.com/xxxxx")
            self.console.print("    · 作者 ID：  3x...")
            self.console.print()
            self.console.print("  📌 其他参数说明：")
            self.console.print("    root        - 下载目录，默认 ./Download")
            self.console.print("    folder_name - 下载文件夹名，默认 Download")
            self.console.print("    name_format - 文件命名格式")
            self.console.print("    proxy       - 代理地址，如 http://127.0.0.1:7890")
            self.console.print("    max_workers - 并发数，默认 4")
            self.console.print("    timeout     - 请求超时(秒)，默认 10")
            self.console.print("    max_retry   - 最大重试次数，默认 5")
            self.console.print()
            self.console.print("=" * 50)
            self.console.print()
        return data

    def _check(self, data: dict) -> dict:
        """检查并补充缺失的配置项"""
        update = False
        for key, value in self._default().items():
            if key not in data:
                data[key] = value
                update = True
                if self.console:
                    self.console.info(
                        f"配置文件 settings.json 缺少参数 {key}，已自动添加默认值！"
                    )
        if update:
            self.update(data)
        return data

    def update(self, data: dict):
        from json import dump
        target = VOLUME_ROOT.joinpath("settings.json")
        if getattr(sys, 'frozen', False):
            pass
        else:
            target = PROJECT_ROOT.joinpath("settings.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding=self.encode) as f:
            dump(data, f, ensure_ascii=False, indent=4)

    def _default(self) -> dict:
        return {
            "mapping_data": {
                "作者ID(AuthorID)": "作者别名(AuthorAlias)",
            },
            "work_path": "",
            "root": "",
            "folder_name": "Download",
            "name_format": "发布日期 作者昵称 作品描述",
            "name_length": 128,
            "cookie": "",
            "ks_cookie": "",
            "proxy": None,
            "data_record": False,
            "max_workers": 4,
            "cover": "",
            "music": False,
            "max_retry": RETRY,
            "timeout": TIMEOUT,
            "chunk": 2 * 1024 * 1024,
            "user_agent": PC_USERAGENT,
            "folder_mode": False,
            "author_archive": False,
            "ks_accounts": [
                {
                    "mark": "示例作者（请修改）",
                    "url": "https://www.kuaishou.com/profile/3x...",
                    "earliest": "",
                    "latest": "",
                    "enable": True,
                }
            ],
        }

    def compatible(self):
        """兼容旧版 config.yaml：如果存在则迁移到 settings.json"""
        old_config = PROJECT_ROOT.joinpath("config.yaml")
        if old_config.exists() and self.file.exists():
            try:
                with old_config.open("r", encoding=self.encode) as f:
                    old_data = safe_load(f)
                if isinstance(old_data, dict):
                    current = self.read()
                    # 将 config.yaml 中独有的字段合并过来
                    for key in self._default():
                        if key in old_data and key not in current:
                            current[key] = old_data[key]
                    self.update(current)
                    # 重命名旧文件为 .bak
                    backup = PROJECT_ROOT.joinpath("config.yaml.bak")
                    move(old_config, backup)
                    if self.console:
                        self.console.info(
                            "检测到旧版 config.yaml，已自动迁移至 settings.json\n"
                            "原文件已重命名为 config.yaml.bak"
                        )
            except Exception:
                pass
