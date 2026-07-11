# 原生桌面模式 + Windows 客户端打包 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 CloakBrowser-Manager 在"原生模式"下点击 Launch 直接在 Windows 桌面弹出指纹浏览器窗口，并打包为单机客户端，同时完整保留现有 Docker + VNC 远程模式。

**Architecture:** 引入单一运行时开关 `use_vnc()`（由 `USE_VNC` 环境变量或 `Xvnc` 探测决定）。后端 `BrowserManager.launch()` 在若干分支点上按模式选择：VNC 模式维持现状；原生模式跳过虚拟显示器、不设 `DISPLAY`、用真实 GPU、传 `--window-size`。前端按 `/api/status` 返回的 `display_mode` 分流渲染（noVNC viewer / 原生状态面板）。新增 `desktop/` 目录：用 pywebview 承载现有 React UI、同进程跑 uvicorn、pystray 托盘、关窗询问，PyInstaller 打成 onedir 客户端。浏览器内核不打包，首启由 `ensure_binary()` 下载。

**Tech Stack:** Python 3.12 / FastAPI / uvicorn（后端），React 19 + TypeScript + Vite + Tailwind（前端），pywebview（Edge WebView2）+ pystray + Pillow（桌面壳），PyInstaller（打包）。测试：pytest（asyncio_mode=auto）、vitest。

## Global Constraints

- **目标平台仅 Windows x64**；不实现 macOS / Linux 客户端打包。
- **双模式共存**：不得改变 Docker/VNC 模式的任何现有行为；VNC 相关代码零删除。
- **模式判定以"是否使用 VNC"为轴，不以操作系统为轴**。判定集中在 `backend/config.py` 的 `use_vnc()`，进程启动确定一次。
- **用户显式设置的环境变量永远优先**（`USE_VNC`、`DATA_DIR`、`CLOAK_PORT`）。
- **浏览器内核不打包**（CloakBrowser 二进制许可证禁止再分发）；首启由官方渠道下载。
- **默认端口 `127.0.0.1:8977`**（env `CLOAK_PORT` 可改）。
- 后端 Python ≥ 3.12；桌面依赖单列 `desktop/requirements.txt`，**不污染** `backend/requirements.txt`（Docker 镜像不变）。
- 测试框架沿用现有：后端 `pytest`（`pyproject.toml` 已配 `asyncio_mode=auto`、`testpaths=["backend/tests"]`），前端 `vitest`。
- 提交信息使用 Conventional Commits；每个 Task 末尾单独 commit。

---

## 阶段总览

- **阶段 A（Task 1–6）**：后端双模式核心。
- **阶段 B（Task 7–8）**：浏览器内核下载状态管理。
- **阶段 C（Task 9–13）**：前端模式分流 + 原生面板 + 关窗模态。
- **阶段 D（Task 14–18）**：桌面壳（pywebview + 托盘 + 关窗逻辑）。
- **阶段 E（Task 19–20）**：冻结资源解析 + PyInstaller 打包 + 手动验收。

每个阶段结束后可独立运行测试。阶段 D、E 的多数验证是 Windows 手动验收（需真实 `cloakbrowser` 二进制与 GUI），已在对应 Task 标注。

---

## Task 1: 预检——验证 cloakbrowser 外部 API

**目的：** 设计依赖 `cloakbrowser` 包的三个未确认细节（spec §11）。本 Task 无代码产出，仅在 Windows 上跑几条命令记录结论，决定 Task 5 / Task 7 的实现分支。**必须最先完成。**

**Files:**
- Create: `docs/superpowers/plans/task1-preflight-findings.md`（记录结论）

- [ ] **Step 1: 在 backend 的 .venv 安装 cloakbrowser 并触发一次下载**

Run:
```bash
cd /d/Develop/Projects/CloakBrowser-Manager/backend
.venv/Scripts/python.exe -m pip install "cloakbrowser[geoip]>=0.3.31"
.venv/Scripts/python.exe -c "from cloakbrowser.download import ensure_binary; print(ensure_binary())"
```
Expected: 打印二进制路径或 None；无异常即视为成功。记录 `ensure_binary()` 的返回值类型与下载目录。

- [ ] **Step 2: 检查 `no_viewport` 是否被 `launch_persistent_context_async` 接受**

Run:
```bash
.venv/Scripts/python.exe -c "import inspect, cloakbrowser; print(inspect.signature(cloakbrowser.launch_persistent_context_async))"
```
记录签名。判断依据：
- 若签名含 `no_viewport` 或 `**kwargs`（透传 Playwright）→ Task 5 用 `no_viewport=True`。
- 若都没有 → Task 5 退化为 `viewport={"width": sw, "height": sh}`（不减 133）。

- [ ] **Step 3: 检查是否有"二进制是否就绪"的查询 API**

Run:
```bash
.venv/Scripts/python.exe -c "import cloakbrowser.download as d; print([n for n in dir(d) if not n.startswith('__')])"
```
记录是否存在 `binary_path` / `is_installed` 之类函数。判断依据：
- 有 → Task 7 用它做快速就绪检查。
- 无 → Task 7 依赖 `ensure_binary()` 幂等性（已安装时快速返回）。

- [ ] **Step 4: 记录结论并提交**

把三步结论写入 `docs/superpowers/plans/task1-preflight-findings.md`（每条一行：`no_viewport: 支持/不支持`、`ensure_binary 返回: ...`、`就绪查询 API: <名字或"无">`）。

```bash
git add docs/superpowers/plans/task1-preflight-findings.md
git commit -m "docs: record cloakbrowser preflight API findings"
```

> 后续 Task 5、Task 7 的代码块以"支持 no_viewport"和"无就绪查询 API"为默认写法；若预检结论相反，按 Task 内的「预检回退」注释调整。

---

## Task 2: `backend/config.py` — 运行时模式与路径解析

**Files:**
- Create: `backend/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces:
  - `use_vnc() -> bool`
  - `display_mode() -> str`（返回 `"vnc"` 或 `"native"`）
  - `get_data_dir() -> pathlib.Path`
  - `frontend_dir() -> pathlib.Path`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config.py`:
```python
"""Tests for runtime mode + path resolution."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend import config


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("off", False), ("", None),
])
def test_use_vnc_explicit_env(monkeypatch, raw, expected):
    monkeypatch.setenv("USE_VNC", raw)
    if expected is None:
        # empty string falls through to auto-detect; force which() to None
        monkeypatch.setattr(config.shutil, "which", lambda _: None)
        assert config.use_vnc() is False
    else:
        assert config.use_vnc() is expected


def test_use_vnc_autodetect_xvnc_present(monkeypatch):
    monkeypatch.delenv("USE_VNC", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/Xvnc")
    assert config.use_vnc() is True


def test_use_vnc_autodetect_xvnc_absent(monkeypatch):
    monkeypatch.delenv("USE_VNC", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    assert config.use_vnc() is False


def test_display_mode_strings(monkeypatch):
    monkeypatch.setenv("USE_VNC", "1")
    assert config.display_mode() == "vnc"
    monkeypatch.setenv("USE_VNC", "0")
    assert config.display_mode() == "native"


def test_get_data_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert config.get_data_dir() == tmp_path


def test_get_data_dir_windows_default(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    assert config.get_data_dir() == Path(r"C:\Users\me\AppData\Roaming") / "CloakBrowser-Manager"


def test_get_data_dir_posix_default(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    assert config.get_data_dir() == Path("/data")


def test_frontend_dir_not_frozen(monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    d = config.frontend_dir()
    assert d.parts[-2:] == ("frontend", "dist")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager && backend/.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -q`
Expected: FAIL —「ModuleNotFoundError: No module named 'backend.config'」

- [ ] **Step 3: 写实现**

Create `backend/config.py`:
```python
"""Runtime configuration: display mode and path resolution.

The single axis is *whether VNC is used*, never the operating system.
Resolved fresh on each call; callers cache at startup if needed.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def use_vnc() -> bool:
    """Return True if profiles should render through VNC.

    USE_VNC=1/true/... → VNC; USE_VNC=0/false/... → native.
    Unset or unrecognized → auto-detect: Xvnc on PATH ⇒ VNC.
    """
    raw = os.environ.get("USE_VNC")
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUTHY:
            return True
        if val in _FALSY:
            return False
    return shutil.which("Xvnc") is not None


def display_mode() -> str:
    """"vnc" or "native" — the string form exposed to the frontend."""
    return "vnc" if use_vnc() else "native"


def get_data_dir() -> Path:
    """Resolve the data directory.

    DATA_DIR env wins. Else Windows → %APPDATA%\\CloakBrowser-Manager,
    other platforms → /data (Docker default, unchanged).
    """
    raw = os.environ.get("DATA_DIR")
    if raw:
        return Path(raw)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "CloakBrowser-Manager"
    return Path("/data")


def frontend_dir() -> Path:
    """Locate the built React SPA, in both source and PyInstaller-frozen runs."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "frontend" / "dist"
    return Path(__file__).parent.parent / "frontend" / "dist"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -q`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/tests/test_config.py
git commit -m "feat(backend): add config module for VNC/native mode + path resolution"
```

---

## Task 3: 将 config 接入 database.py 与 main.py 静态目录

**Files:**
- Modify: `backend/database.py:14-15`
- Modify: `backend/main.py:180`
- Test: 复用现有 `backend/tests`（回归）

**Interfaces:**
- Consumes: `config.get_data_dir()`, `config.frontend_dir()`（Task 2）

- [ ] **Step 1: 改 database.py 用 get_data_dir()**

在 `backend/database.py` 顶部 import 区加入，并替换硬编码路径。

将 14-15 行：
```python
DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "profiles.db"
```
改为：
```python
from .config import get_data_dir

DATA_DIR = get_data_dir()
DB_PATH = DATA_DIR / "profiles.db"
```
（`from pathlib import Path` 已存在，保留。测试通过 monkeypatch 覆盖 `db.DATA_DIR` / `db.DB_PATH`，模块级函数在调用时读全局，故行为不变。）

- [ ] **Step 2: 改 main.py 用 frontend_dir()**

将 `backend/main.py:180`：
```python
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
```
改为：
```python
from .config import frontend_dir

FRONTEND_DIR = frontend_dir()
```
（把 `from .config import frontend_dir` 放到文件已有的 import 区；`Path` 仍在别处使用，保留导入。）

- [ ] **Step 3: 运行完整后端测试回归**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: PASS（与改动前数量一致，无新增失败）

- [ ] **Step 4: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "refactor(backend): resolve data dir and frontend dir via config"
```

---

## Task 4: models.py — 可空 Launch 字段 + display_mode

**Files:**
- Modify: `backend/models.py:108-119`
- Test: `backend/tests/test_models.py`（追加）

**Interfaces:**
- Produces:
  - `LaunchResponse.vnc_ws_port: int | None`
  - `LaunchResponse.display: str | None`
  - `StatusResponse.display_mode: str`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_models.py` 末尾追加：
```python
def test_launch_response_allows_null_vnc_fields():
    from backend.models import LaunchResponse
    r = LaunchResponse(profile_id="abc", cdp_url="/api/profiles/abc/cdp")
    assert r.vnc_ws_port is None
    assert r.display is None
    assert r.status == "running"


def test_status_response_has_display_mode():
    from backend.models import StatusResponse
    s = StatusResponse(
        running_count=0, binary_version="x", profiles_total=0, display_mode="native"
    )
    assert s.display_mode == "native"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -q`
Expected: FAIL —`LaunchResponse` 缺省需要 `vnc_ws_port`/`display`；`StatusResponse` 无 `display_mode`

- [ ] **Step 3: 写实现**

将 `backend/models.py` 的 `LaunchResponse`（108-113 行附近）改为：
```python
class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None
```

将 `StatusResponse`（116-119 行附近）改为：
```python
class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    profiles_total: int
    display_mode: str = "vnc"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/tests/test_models.py
git commit -m "feat(backend): make launch response VNC fields optional, add display_mode"
```

---

## Task 5: browser_manager.py — 原生模式分支

**Files:**
- Modify: `backend/browser_manager.py`（`RunningProfile`、`launch()`、`_on_browser_closed()`、`stop()`、`get_status()`、`_build_fingerprint_args()`）
- Test: `backend/tests/test_browser_manager_native.py`

**Interfaces:**
- Consumes: `config.use_vnc()`（Task 2）
- Produces:
  - `RunningProfile.display: int | None`、`RunningProfile.ws_port: int | None`
  - `_build_fingerprint_args(profile, native: bool = False) -> list[str]`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_browser_manager_native.py`:
```python
"""Native-mode launch branch of BrowserManager."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import browser_manager as bm


def _make_context_mock():
    ctx = MagicMock()
    ctx.add_init_script = AsyncMock()
    ctx.pages = []
    ctx.on = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_native_launch_skips_vnc_and_display(monkeypatch, tmp_path):
    monkeypatch.setattr(bm, "use_vnc", lambda: False)

    fake_launch = AsyncMock(return_value=_make_context_mock())
    monkeypatch.setattr(bm, "launch_persistent_context_async", fake_launch)

    mgr = bm.BrowserManager()
    mgr.vnc.allocate = AsyncMock()
    mgr.vnc.start_vnc = AsyncMock()

    profile = {
        "id": "p1",
        "user_data_dir": str(tmp_path / "p1"),
        "screen_width": 1440,
        "screen_height": 900,
    }
    running = await mgr.launch(profile)

    # VNC untouched
    mgr.vnc.allocate.assert_not_called()
    mgr.vnc.start_vnc.assert_not_called()
    assert running.display is None
    assert running.ws_port is None

    kwargs = fake_launch.call_args.kwargs
    # No DISPLAY injected
    assert "DISPLAY" not in kwargs.get("env", {})
    # Real GPU (no swiftshader), window sized to the profile
    assert "--use-angle=swiftshader" not in kwargs["args"]
    assert "--window-size=1440,900" in kwargs["args"]
    # No forced viewport in native mode
    assert kwargs.get("no_viewport") is True


def test_build_fingerprint_args_native_omits_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=True)
    assert "--use-angle=swiftshader" not in args
    assert "--fingerprint=7" in args


def test_build_fingerprint_args_vnc_keeps_swiftshader():
    mgr = bm.BrowserManager()
    args = mgr._build_fingerprint_args({"fingerprint_seed": 7}, native=False)
    assert "--use-angle=swiftshader" in args
```

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_browser_manager_native.py -q`
Expected: FAIL —`bm.use_vnc` 不存在 / `_build_fingerprint_args` 不接受 `native`

- [ ] **Step 3: 加 import 与 dataclass 可空字段**

在 `backend/browser_manager.py` 顶部 import 区（`from .vnc_manager import VNCManager` 之后）加：
```python
from .config import use_vnc
```

将 `RunningProfile`（149-155 行附近）改为：
```python
@dataclass
class RunningProfile:
    profile_id: str
    context: Any  # Playwright BrowserContext
    display: int | None
    ws_port: int | None
    cdp_port: int
```

- [ ] **Step 4: 改 `launch()` 加原生分支**

将 `launch()` 从 VNC 分配到 `launch_persistent_context_async` 调用这一段（约 167-234 行）替换为：
```python
    async def launch(self, profile: dict[str, Any]) -> RunningProfile:
        """Launch a browser instance for the given profile."""
        profile_id = profile["id"]

        async with self._lock:
            if profile_id in self.running or profile_id in self._launching:
                raise RuntimeError(f"Profile {profile_id} is already running")
            self._launching.add(profile_id)

        native = not use_vnc()

        display: int | None = None
        ws_port: int | None = None
        if not native:
            display, ws_port = await self.vnc.allocate()

        try:
            cdp_port = self._allocate_cdp_port()
        except ValueError:
            async with self._lock:
                self._launching.discard(profile_id)
            if display is not None:
                await self.vnc.stop_vnc(display)
            raise

        # Clean stale Chromium lock files (left by previous crashes)
        user_data_dir = Path(profile["user_data_dir"])
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (user_data_dir / lock_file).unlink(missing_ok=True)

        # Set up bookmarks and search engine on first launch
        _init_profile_defaults(user_data_dir)

        try:
            if not native:
                await self.vnc.start_vnc(
                    display,
                    ws_port,
                    width=profile.get("screen_width", 1920),
                    height=profile.get("screen_height", 1080),
                )

            # Build fingerprint args from profile settings
            extra_args = self._build_fingerprint_args(profile, native=native)
            extra_args += profile.get("launch_args") or []
            extra_args.append(f"--remote-debugging-port={cdp_port}")
            if native:
                sw = profile.get("screen_width", 1920)
                sh = profile.get("screen_height", 1080)
                extra_args.append(f"--window-size={sw},{sh}")

            # Normalize proxy format
            raw_proxy = profile.get("proxy") or None
            proxy = _normalize_proxy(raw_proxy) if raw_proxy else None
            if proxy:
                _validate_proxy(proxy)

            launch_kwargs: dict[str, Any] = dict(
                user_data_dir=profile["user_data_dir"],
                headless=bool(profile.get("headless", False)),
                proxy=proxy,
                args=extra_args,
                timezone=profile.get("timezone") or None,
                locale=profile.get("locale") or None,
                humanize=bool(profile.get("humanize", False)),
                human_preset=profile.get("human_preset", "default"),
                geoip=bool(profile.get("geoip", False)),
                color_scheme=profile.get("color_scheme") or None,
                user_agent=profile.get("user_agent") or None,
            )
            if native:
                # Native window: real desktop display, no forced viewport.
                # 预检回退：若 no_viewport 不被支持，改为
                #   launch_kwargs["viewport"] = {
                #       "width": profile.get("screen_width", 1920),
                #       "height": profile.get("screen_height", 1080),
                #   }
                launch_kwargs["no_viewport"] = True
            else:
                # VNC: browser fills the virtual display; -133 compensates UI chrome.
                launch_kwargs["viewport"] = {
                    "width": profile.get("screen_width", 1920),
                    "height": profile.get("screen_height", 1080) - 133,
                }
                launch_kwargs["env"] = {**os.environ, "DISPLAY": f":{display}"}

            context = await launch_persistent_context_async(**launch_kwargs)
```
（此段之后的 `_clipboard_init_js` 注入、`RunningProfile(...)` 构造、`context.on("close", ...)`、`self.running[...] = running`、日志、`return running` 与 `except BaseException` 清理块保持不变——但见 Step 5 对 except 块的小改。）

- [ ] **Step 5: 修 launch() 的失败清理与 RunningProfile 构造**

`launch()` 内构造 `RunningProfile(...)` 处已用局部变量 `display`/`ws_port`，无需改。将末尾的失败清理块（283-287 行附近）：
```python
        except BaseException:
            async with self._lock:
                self._launching.discard(profile_id)
            await self.vnc.stop_vnc(display)
            raise
```
改为：
```python
        except BaseException:
            async with self._lock:
                self._launching.discard(profile_id)
            if display is not None:
                await self.vnc.stop_vnc(display)
            raise
```

- [ ] **Step 6: 修 `_on_browser_closed()` 与 `stop()` 的 VNC 清理守卫**

`_on_browser_closed()`（289-296 行附近）中：
```python
        if running:
            logger.info("Browser closed for profile %s, cleaning up", profile_id)
            await self.vnc.stop_vnc(running.display)
```
改为：
```python
        if running:
            logger.info("Browser closed for profile %s, cleaning up", profile_id)
            if running.display is not None:
                await self.vnc.stop_vnc(running.display)
```

`stop()`（298-314 行附近）末尾：
```python
        await self.vnc.stop_vnc(running.display)
```
改为：
```python
        if running.display is not None:
            await self.vnc.stop_vnc(running.display)
```

- [ ] **Step 7: 修 `get_status()` 的 display 空值**

`get_status()`（316-326 行附近）改为：
```python
    def get_status(self, profile_id: str) -> dict[str, Any]:
        running = self.running.get(profile_id)
        if running:
            return {
                "status": "running",
                "vnc_ws_port": running.ws_port,
                "display": f":{running.display}" if running.display is not None else None,
                "cdp_url": f"/api/profiles/{profile_id}/cdp",
            }
        return {"status": "stopped", "vnc_ws_port": None, "display": None, "cdp_url": None}
```

- [ ] **Step 8: 给 `_build_fingerprint_args` 加 `native` 参数**

将签名与前 3 行（379-385 行附近）：
```python
    def _build_fingerprint_args(self, profile: dict[str, Any]) -> list[str]:
        """Build extra Chromium args from profile fingerprint settings."""
        args: list[str] = [
            "--disable-infobars",
            "--test-type",  # suppress "unsupported flag: --no-sandbox" bad flags warning
            "--use-angle=swiftshader",  # software GL for VNC (no GPU in container)
        ]
```
改为：
```python
    def _build_fingerprint_args(
        self, profile: dict[str, Any], native: bool = False
    ) -> list[str]:
        """Build extra Chromium args from profile fingerprint settings."""
        args: list[str] = ["--disable-infobars", "--test-type"]
        if not native:
            # Software GL for VNC (no GPU in container). Native mode uses the real GPU.
            args.append("--use-angle=swiftshader")
```
（其余 seed/platform/gpu/screen 逻辑不变。）

- [ ] **Step 9: 运行新测试 + 完整回归**

Run:
```bash
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_browser_manager_native.py -q
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```
Expected: 新测试 PASS；完整套件无新增失败。

- [ ] **Step 10: Commit**

```bash
git add backend/browser_manager.py backend/tests/test_browser_manager_native.py
git commit -m "feat(backend): add native launch branch (skip VNC, real GPU, window-size)"
```

---

## Task 6: main.py — status 暴露模式、launch 空值安全、clipboard 原生 501

**Files:**
- Modify: `backend/main.py`（`get_system_status`、`launch_profile`、两个 clipboard 端点）
- Test: `backend/tests/test_api.py`（追加 + 更新现有 clipboard 测试）

**Interfaces:**
- Consumes: `config.display_mode()`, `config.use_vnc()`（Task 2）；`LaunchResponse` 可空字段、`StatusResponse.display_mode`（Task 4）

- [ ] **Step 1: 在 main.py import config 的两个函数**

在 `backend/main.py` 已有的 `from .config import frontend_dir`（Task 3 加的）改为：
```python
from .config import display_mode, frontend_dir, use_vnc
```

- [ ] **Step 2: 写/改失败测试**

在 `backend/tests/test_api.py` 顶部（`from backend import main` 之后）确保可 patch。追加新测试并**更新现有 clipboard 测试**使其显式跑在 VNC 模式。

追加：
```python
def test_status_reports_display_mode(app_client: TestClient, monkeypatch):
    monkeypatch.setattr(main, "display_mode", lambda: "native")
    resp = app_client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["display_mode"] == "native"


def test_set_clipboard_501_in_native_mode(app_client: TestClient, monkeypatch):
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    create = app_client.post("/api/profiles", json={"name": "N"})
    pid = create.json()["id"]
    # inject a running profile so the mode guard is what rejects, not "not running"
    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = None
    main.browser_mgr.running[pid] = mock_running
    resp = app_client.post(f"/api/profiles/{pid}/clipboard", json={"text": "x"})
    assert resp.status_code == 501
    main.browser_mgr.running.pop(pid, None)


def test_get_clipboard_501_in_native_mode(app_client: TestClient, monkeypatch):
    monkeypatch.setattr(main, "use_vnc", lambda: False)
    create = app_client.post("/api/profiles", json={"name": "N"})
    pid = create.json()["id"]
    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = None
    main.browser_mgr.running[pid] = mock_running
    resp = app_client.get(f"/api/profiles/{pid}/clipboard")
    assert resp.status_code == 501
    main.browser_mgr.running.pop(pid, None)
```

找到 `test_api.py` 中现有的 clipboard 测试（约 265 行的 fixture / 相关用例），在其调用 clipboard 端点前加一行强制 VNC 模式：
```python
    monkeypatch.setattr(main, "use_vnc", lambda: True)
```
（若现有 clipboard 测试用的是共享 fixture，则在该 fixture 内加此 patch。目的：现有 VNC 剪贴板行为在测试里显式跑在 VNC 模式，不受默认自动探测影响。）

- [ ] **Step 3: 运行测试确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -q`
Expected: FAIL —status 无 `display_mode`；clipboard 原生模式未返回 501

- [ ] **Step 4: 改 `get_system_status`**

将 `get_system_status`（570-579 行附近）改为：
```python
@app.get("/api/status", response_model=StatusResponse)
async def get_system_status():
    from cloakbrowser.config import CHROMIUM_VERSION

    profiles = db.list_profiles()
    return StatusResponse(
        running_count=len(browser_mgr.running),
        binary_version=CHROMIUM_VERSION,
        profiles_total=len(profiles),
        display_mode=display_mode(),
    )
```

- [ ] **Step 5: 改 `launch_profile` 的 display 空值**

将 `launch_profile` 的 `return LaunchResponse(...)`（541-547 行附近）改为：
```python
    return LaunchResponse(
        profile_id=profile_id,
        status="running",
        vnc_ws_port=running.ws_port,
        display=f":{running.display}" if running.display is not None else None,
        cdp_url=f"/api/profiles/{profile_id}/cdp",
    )
```

- [ ] **Step 6: 两个 clipboard 端点加原生守卫**

在 `set_clipboard`（590 行附近）函数体第一行、取 `running` 之前插入：
```python
    if not use_vnc():
        raise HTTPException(status_code=501, detail="Clipboard relay is VNC-only")
```
在 `get_clipboard`（621 行附近）函数体第一行、取 `running` 之前插入同样两行。

- [ ] **Step 7: 运行测试确认通过 + 完整回归**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: PASS（全部）

- [ ] **Step 8: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): expose display_mode, null-safe launch, native clipboard 501"
```

---

## Task 7: `backend/binary_manager.py` — 内核就绪状态与后台下载

**Files:**
- Create: `backend/binary_manager.py`
- Test: `backend/tests/test_binary_manager.py`

**Interfaces:**
- Produces:
  - `class BinaryManager`，属性 `ready: bool` / `downloading: bool` / `error: str | None`
  - `status() -> dict`（键：`ready`、`downloading`、`error`）
  - `start() -> None`（幂等：已就绪或下载中则不重复启动后台任务）
  - `async wait_ready() -> bool`

- [ ] **Step 1: 在 conftest 补 cloakbrowser.download 的 mock**

`backend/tests/conftest.py` 顶部已 mock `cloakbrowser` 与 `cloakbrowser.config`。追加（在 `sys.modules.setdefault("cloakbrowser.config", _mock_config)` 之后）：
```python
_mock_download = types.ModuleType("cloakbrowser.download")
_mock_download.ensure_binary = MagicMock(return_value="/fake/chrome")  # type: ignore[attr-defined]
sys.modules.setdefault("cloakbrowser.download", _mock_download)
```

- [ ] **Step 2: 写失败测试**

Create `backend/tests/test_binary_manager.py`:
```python
"""Tests for BinaryManager background download state machine."""
from __future__ import annotations

import sys

import pytest

from backend.binary_manager import BinaryManager


@pytest.mark.asyncio
async def test_start_then_wait_ready_success(monkeypatch):
    calls = {"n": 0}

    def fake_ensure():
        calls["n"] += 1
        return "/fake/chrome"

    monkeypatch.setattr(sys.modules["cloakbrowser.download"], "ensure_binary", fake_ensure)

    m = BinaryManager()
    assert m.status() == {"ready": False, "downloading": False, "error": None}
    m.start()
    assert m.downloading is True
    ok = await m.wait_ready()
    assert ok is True
    assert m.ready is True
    assert m.downloading is False
    assert m.error is None
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_download_failure_records_error(monkeypatch):
    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(sys.modules["cloakbrowser.download"], "ensure_binary", boom)

    m = BinaryManager()
    m.start()
    ok = await m.wait_ready()
    assert ok is False
    assert m.ready is False
    assert m.downloading is False
    assert "network down" in m.error


@pytest.mark.asyncio
async def test_start_is_idempotent_when_downloading(monkeypatch):
    monkeypatch.setattr(
        sys.modules["cloakbrowser.download"], "ensure_binary", lambda: "/fake/chrome"
    )
    m = BinaryManager()
    m.start()
    first_task = m._task
    m.start()  # should not replace the in-flight task
    assert m._task is first_task
    await m.wait_ready()
```

- [ ] **Step 3: 运行测试确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_manager.py -q`
Expected: FAIL —`No module named 'backend.binary_manager'`

- [ ] **Step 4: 写实现**

Create `backend/binary_manager.py`:
```python
"""Track CloakBrowser binary readiness and download it in the background.

The binary is downloaded from official channels on first run (~200 MB).
`ensure_binary()` is idempotent — on warm starts it returns quickly, so
`start()` is safe to call on every launch regardless of mode.

预检（Task 1）：若 cloakbrowser.download 提供了就绪查询函数（如 binary_path），
可在 start() 里先做一次同步存在性检查，命中则直接 ready=True 而不起后台任务。
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("cloakbrowser.manager.binary")


class BinaryManager:
    def __init__(self) -> None:
        self.ready: bool = False
        self.downloading: bool = False
        self.error: str | None = None
        self._task: asyncio.Task | None = None

    def status(self) -> dict[str, object]:
        return {"ready": self.ready, "downloading": self.downloading, "error": self.error}

    def start(self) -> None:
        """Kick off a background download unless already ready or in flight."""
        if self.ready or self.downloading:
            return
        self.downloading = True
        self.error = None
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            from cloakbrowser.download import ensure_binary

            await asyncio.to_thread(ensure_binary)
            self.ready = True
            self.error = None
            logger.info("CloakBrowser binary is ready")
        except Exception as exc:  # noqa: BLE001 — surface any download failure to the UI
            self.error = str(exc)
            logger.error("Binary download failed: %s", exc)
        finally:
            self.downloading = False

    async def wait_ready(self) -> bool:
        """Await the in-flight download (if any) and report readiness."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        return self.ready
```

- [ ] **Step 5: 运行测试确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_binary_manager.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/binary_manager.py backend/tests/test_binary_manager.py backend/tests/conftest.py
git commit -m "feat(backend): add BinaryManager for background kernel download"
```

---

## Task 8: main.py — 内核状态端点 + lifespan 接线

**Files:**
- Modify: `backend/main.py`（新增单例 `binary_mgr`、两个端点、`lifespan`、启动自动下载与延后 auto_launch）
- Test: `backend/tests/test_api.py`（追加）

**Interfaces:**
- Consumes: `BinaryManager`（Task 7）
- Produces:
  - `GET /api/binary/status` → `{ready, downloading, error}`
  - `POST /api/binary/download` → `{ok: true}`（触发/重试下载）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_api.py` 追加：
```python
def test_binary_status_endpoint(app_client: TestClient):
    resp = app_client.get("/api/binary/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"ready", "downloading", "error"}


def test_binary_download_endpoint_triggers_start(app_client: TestClient, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main.binary_mgr, "start", lambda: called.__setitem__("n", called["n"] + 1))
    resp = app_client.post("/api/binary/download")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert called["n"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k binary -q`
Expected: FAIL —端点不存在（404）

- [ ] **Step 3: 新增单例并接线 lifespan**

在 `backend/main.py` 的 `browser_mgr = BrowserManager()`（177 行附近）之后加：
```python
from .binary_manager import BinaryManager

binary_mgr = BinaryManager()
```

将 `lifespan`（375-386 行附近）改为：
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await browser_mgr.cleanup_stale()
    binary_mgr.start()  # background kernel download (idempotent on warm starts)
    browser_mgr._auto_launch_task = asyncio.create_task(_startup_autolaunch())
    logger.info("CloakBrowser Manager started")
    yield
    logger.info("Shutting down — stopping all browsers...")
    if browser_mgr._auto_launch_task and not browser_mgr._auto_launch_task.done():
        browser_mgr._auto_launch_task.cancel()
        await asyncio.gather(browser_mgr._auto_launch_task, return_exceptions=True)
    await browser_mgr.cleanup_all()


async def _startup_autolaunch():
    """Wait for the binary to be ready, then auto-launch flagged profiles."""
    await binary_mgr.wait_ready()
    await browser_mgr.auto_launch_all()
```

- [ ] **Step 4: 加两个端点**

在 `get_system_status` 之后（System Status 区块内）加：
```python
@app.get("/api/binary/status")
async def get_binary_status():
    return binary_mgr.status()


@app.post("/api/binary/download")
async def start_binary_download():
    binary_mgr.start()
    return {"ok": True}
```

- [ ] **Step 5: 运行测试确认通过 + 完整回归**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: PASS（全部）

> 注：`app_client` fixture 用 `TestClient(main.app)` 作为上下文管理器会触发 lifespan。`binary_mgr.start()` 内 `ensure_binary` 已被 conftest mock，`_startup_autolaunch` 会等待并调用 `auto_launch_all`（无 auto_launch profile 时立即返回）。若测试中出现悬挂，确认 conftest 的 `cloakbrowser.download.ensure_binary` mock 为同步 MagicMock（非阻塞）。

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_api.py
git commit -m "feat(backend): add binary status/download endpoints, gate auto-launch on readiness"
```

---

## Task 9: 前端 api.ts — 类型与内核端点

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`（追加）

**Interfaces:**
- Produces:
  - `SystemStatus.display_mode: "native" | "vnc"`
  - `interface BinaryStatus { ready: boolean; downloading: boolean; error: string | null }`
  - `api.getBinaryStatus()`, `api.downloadBinary()`
  - `LaunchResult.vnc_ws_port: number | null`、`display: string | null`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/lib/api.test.ts` 追加：
```typescript
describe("api.getBinaryStatus", () => {
  it("GETs binary status", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ ready: false, downloading: true, error: null }),
    );
    const result = await api.getBinaryStatus();
    expect(result.downloading).toBe(true);
    expect(mockFetch.mock.calls[0][0]).toBe("/api/binary/status");
  });
});

describe("api.downloadBinary", () => {
  it("POSTs to trigger download", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
    await api.downloadBinary();
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/binary/download");
    expect(options.method).toBe("POST");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager/frontend && pnpm test -- api.test`
Expected: FAIL —`api.getBinaryStatus is not a function`

- [ ] **Step 3: 改类型 + 加端点**

在 `frontend/src/lib/api.ts`：

`SystemStatus`（70-74 行）改为：
```typescript
export interface SystemStatus {
  running_count: number;
  binary_version: string;
  profiles_total: number;
  display_mode: "native" | "vnc";
}

export interface BinaryStatus {
  ready: boolean;
  downloading: boolean;
  error: string | null;
}
```

`LaunchResult`（62-68 行）的两字段改为可空：
```typescript
export interface LaunchResult {
  profile_id: string;
  status: string;
  vnc_ws_port: number | null;
  display: string | null;
  cdp_url: string | null;
}
```

在 `api` 对象末尾（`getClipboard` 之后）加：
```typescript
  getBinaryStatus: () => request<BinaryStatus>("/api/binary/status"),

  downloadBinary: () =>
    request<{ ok: boolean }>("/api/binary/download", { method: "POST" }),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm test -- api.test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(frontend): add display_mode, binary status types and endpoints"
```

---

## Task 10: 前端 RunningPanel 组件

**Files:**
- Create: `frontend/src/components/RunningPanel.tsx`
- Test: `frontend/src/components/RunningPanel.test.tsx`

**Interfaces:**
- Produces: `RunningPanel` — props `{ profileId: string; cdpUrl: string | null }`
  - 渲染运行徽标、桌面窗口提示、CDP URL + 复制按钮。
  - 不自带轮询（状态切换由 App 的全局轮询 + 视图切换 effect 负责，见 Task 11）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/RunningPanel.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RunningPanel } from "./RunningPanel";

beforeEach(() => {
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("RunningPanel", () => {
  it("shows the desktop-window hint", () => {
    render(<RunningPanel profileId="p1" cdpUrl="/api/profiles/p1/cdp" />);
    expect(screen.getByText(/desktop/i)).toBeInTheDocument();
  });

  it("copies the absolute CDP url", async () => {
    render(<RunningPanel profileId="p1" cdpUrl="/api/profiles/p1/cdp" />);
    fireEvent.click(screen.getByRole("button", { name: /copy cdp/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining("/api/profiles/p1/cdp"),
    );
  });

  it("omits the CDP row when cdpUrl is null", () => {
    render(<RunningPanel profileId="p1" cdpUrl={null} />);
    expect(screen.queryByRole("button", { name: /copy cdp/i })).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm test -- RunningPanel`
Expected: FAIL —模块不存在

- [ ] **Step 3: 写实现**

Create `frontend/src/components/RunningPanel.tsx`:
```tsx
import { useState } from "react";
import { Code2, Monitor } from "lucide-react";

interface RunningPanelProps {
  profileId: string;
  cdpUrl: string | null;
}

export function RunningPanel({ profileId: _profileId, cdpUrl }: RunningPanelProps) {
  const [cdpCopied, setCdpCopied] = useState(false);

  const copyCdp = () => {
    if (!cdpUrl) return;
    const abs = `${window.location.protocol}//${window.location.host}${cdpUrl}`;
    navigator.clipboard
      ?.writeText(abs)
      .then(() => {
        setCdpCopied(true);
        setTimeout(() => setCdpCopied(false), 2000);
      })
      .catch((err) => console.warn("[cdp] copy failed:", err));
  };

  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md px-6">
        <div className="flex items-center justify-center mb-4">
          <span className="relative inline-flex h-3 w-3 mr-2">
            <span className="absolute inline-flex h-3 w-3 rounded-full bg-emerald-400 opacity-75 animate-ping" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-400" />
          </span>
          <span className="text-sm font-medium text-gray-200">Running</span>
        </div>

        <Monitor className="h-10 w-10 mx-auto text-gray-500 mb-3" />
        <p className="text-sm text-gray-300 mb-1">
          The browser window is open on your desktop.
        </p>
        <p className="text-xs text-gray-500 mb-6">
          Closing that window (or clicking Stop) ends this session.
        </p>

        {cdpUrl && (
          <button
            onClick={copyCdp}
            aria-label="Copy CDP endpoint"
            className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border ${
              cdpCopied ? "text-emerald-400" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            <Code2 className="h-3.5 w-3.5" />
            {cdpCopied ? "Copied!" : "Copy CDP endpoint"}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm test -- RunningPanel`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RunningPanel.tsx frontend/src/components/RunningPanel.test.tsx
git commit -m "feat(frontend): add RunningPanel for native mode"
```

---

## Task 11: App.tsx — 模式分流、停止切视图、内核横幅

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: 手动（App 集成逻辑，vitest 对 App 成本高，改动小，靠类型检查 + 手动验收）

**Interfaces:**
- Consumes: `api.getStatus()`（`display_mode`）、`api.getBinaryStatus()`、`RunningPanel`（Task 10）
- Produces: `AppContent` 接收 `displayMode: "native" | "vnc"` 与 `binaryReady: boolean`

- [ ] **Step 1: 顶层 App 拉取系统状态与内核状态**

在 `App()` 组件（15-84 行）的 state 区加：
```tsx
  const [displayMode, setDisplayMode] = useState<"native" | "vnc">("vnc");
  const [binary, setBinary] = useState<{ ready: boolean; downloading: boolean; error: string | null }>(
    { ready: true, downloading: false, error: null },
  );
```
在现有 `useEffect`（19-37 行）里，`api.authStatus()` 成功分支之后追加系统状态拉取（放在同一个 effect 内 `.then` 链之外，新起一段）：
```tsx
  useEffect(() => {
    api.getStatus()
      .then((s) => setDisplayMode(s.display_mode))
      .catch((err) => console.warn("[status] failed:", err));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const b = await api.getBinaryStatus();
        if (!cancelled) setBinary(b);
        if (!cancelled && !b.ready) setTimeout(poll, 2000);
      } catch (err) {
        console.warn("[binary] status failed:", err);
      }
    };
    poll();
    return () => { cancelled = true; };
  }, []);
```

将渲染 `AppContent` 处（75-83 行）传入新 props：
```tsx
  return (
    <AppContent
      authRequired={authRequired}
      displayMode={displayMode}
      binary={binary}
      onLogout={async () => {
        await api.logout();
        setAuthState("required");
      }}
    />
  );
```

- [ ] **Step 2: 扩展 AppContentProps 并接收**

`AppContentProps`（86-89 行）改为：
```tsx
interface AppContentProps {
  authRequired: boolean;
  displayMode: "native" | "vnc";
  binary: { ready: boolean; downloading: boolean; error: string | null };
  onLogout: () => void;
}
```
函数签名（91 行）改为：
```tsx
function AppContent({ authRequired, displayMode, binary, onLogout }: AppContentProps) {
```

- [ ] **Step 3: 加"运行中被外部停止 → 切回编辑视图"的 effect**

在 `AppContent` 内、`const selected = ...`（97 行）之后加：
```tsx
  useEffect(() => {
    if (view === "view" && selected && selected.status !== "running") {
      setView("edit");
    }
  }, [view, selected]);
```
（原生模式下用户直接关闭桌面浏览器窗口时，`useProfiles` 的 3 秒轮询把 `status` 更新为 `stopped`，此 effect 将视图切回编辑。）

- [ ] **Step 4: 引入 RunningPanel 并按模式分流**

顶部 import 加：
```tsx
import { RunningPanel } from "./components/RunningPanel";
```
将视图渲染区（245-253 行）：
```tsx
          {view === "view" && selected && selected.status === "running" && (
            <ProfileViewer
              key={selected.id}
              profileId={selected.id}
              cdpUrl={selected.cdp_url}
              clipboardSync={selected.clipboard_sync}
              onDisconnect={handleVncDisconnect}
            />
          )}
```
改为：
```tsx
          {view === "view" && selected && selected.status === "running" && (
            displayMode === "vnc" ? (
              <ProfileViewer
                key={selected.id}
                profileId={selected.id}
                cdpUrl={selected.cdp_url}
                clipboardSync={selected.clipboard_sync}
                onDisconnect={handleVncDisconnect}
              />
            ) : (
              <RunningPanel
                key={selected.id}
                profileId={selected.id}
                cdpUrl={selected.cdp_url}
              />
            )
          )}
```

- [ ] **Step 5: 内核未就绪横幅 + 禁用 Launch**

在错误横幅块（209-213 行）之后加内核横幅：
```tsx
        {!binary.ready && (
          <div className="px-4 py-2 bg-amber-600/15 border-b border-amber-600/30 text-amber-300 text-sm flex items-center justify-between">
            <span>
              {binary.error
                ? `Browser kernel download failed: ${binary.error}`
                : "Downloading browser kernel… Launch is disabled until this finishes."}
            </span>
            {binary.error && (
              <button
                onClick={() => api.downloadBinary().catch(() => {})}
                className="text-xs underline hover:text-amber-200"
              >
                Retry
              </button>
            )}
          </div>
        )}
```
将顶部工具栏的 `LaunchButton`（189-195 行）包一层禁用逻辑——当 `!binary.ready` 时不允许 launch。把：
```tsx
            {selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
```
改为：
```tsx
            {selected && (
              <LaunchButton
                status={selected.status}
                canLaunch={binary.ready}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
```
（`LaunchButton` 的 `canLaunch` 属性在 Task 12 顺带加；此处先写调用点。）

- [ ] **Step 6: 类型检查 + 构建**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager/frontend && pnpm build`
Expected: `tsc -b` 通过（Task 12 加 `canLaunch` 前，这里会因缺 prop 报错——若单独执行本 Task，先在 LaunchButton 接口临时加可选 `canLaunch?: boolean` 占位；Task 12 落实其行为）。为避免顺序耦合，**本 Step 与 Task 12 Step 3 一起构建通过**。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): route by display_mode, stop-on-close, kernel banner"
```

---

## Task 12: LaunchButton 禁用 + ProfileForm 原生隐藏 clipboard_sync

**Files:**
- Modify: `frontend/src/components/LaunchButton.tsx`
- Modify: `frontend/src/components/ProfileForm.tsx`（+ 由 App 传入 `displayMode`）
- Modify: `frontend/src/App.tsx`（给两处 `ProfileForm` 传 `displayMode`）
- Test: `frontend/src/components/LaunchButton.test.tsx`

**Interfaces:**
- Produces:
  - `LaunchButton` 新增 prop `canLaunch?: boolean`（默认 true；false 时停用 Launch）
  - `ProfileForm` 新增 prop `displayMode?: "native" | "vnc"`

- [ ] **Step 1: 写 LaunchButton 失败测试**

Create `frontend/src/components/LaunchButton.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LaunchButton } from "./LaunchButton";

describe("LaunchButton", () => {
  it("disables launch when canLaunch is false", () => {
    const onLaunch = vi.fn();
    render(
      <LaunchButton status="stopped" canLaunch={false} onLaunch={onLaunch} onStop={vi.fn()} />,
    );
    const btn = screen.getByRole("button", { name: /launch/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onLaunch).not.toHaveBeenCalled();
  });

  it("allows launch by default", () => {
    render(<LaunchButton status="stopped" onLaunch={vi.fn()} onStop={vi.fn()} />);
    expect(screen.getByRole("button", { name: /launch/i })).not.toBeDisabled();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- LaunchButton`
Expected: FAIL —禁用态不存在

- [ ] **Step 3: 改 LaunchButton**

`LaunchButtonProps`（4-8 行）加 `canLaunch`：
```tsx
interface LaunchButtonProps {
  status: "running" | "stopped";
  canLaunch?: boolean;
  onLaunch: () => Promise<void>;
  onStop: () => Promise<void>;
}
```
签名（10 行）：
```tsx
export function LaunchButton({ status, canLaunch = true, onLaunch, onStop }: LaunchButtonProps) {
```
把 stopped 分支的返回（50-58 行）改为在 `!canLaunch` 时禁用：
```tsx
  return (
    <div>
      <button
        onClick={handleClick}
        disabled={!canLaunch}
        className={`btn-primary flex items-center gap-1.5 ${!canLaunch ? "opacity-50 cursor-not-allowed" : ""}`}
      >
        <Play className="h-3.5 w-3.5" />
        <span>Launch</span>
      </button>
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
    </div>
  );
```

- [ ] **Step 4: 运行确认通过**

Run: `pnpm test -- LaunchButton`
Expected: PASS

- [ ] **Step 5: ProfileForm 加 displayMode 并隐藏 clipboard_sync**

`ProfileFormProps`（5-10 行）加：
```tsx
  displayMode?: "native" | "vnc";
```
签名（55 行）：
```tsx
export function ProfileForm({ profile, onSave, onDelete, onCancel, displayMode = "vnc" }: ProfileFormProps) {
```
把 clipboard_sync 那段 `<label>`（439-447 行）用条件包裹：
```tsx
            {displayMode === "vnc" && (
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.clipboard_sync ?? true}
                  onChange={(e) => set("clipboard_sync", e.target.checked)}
                  className="rounded border-border bg-surface-2"
                />
                Enable clipboard sync by default in VNC viewer
              </label>
            )}
```

- [ ] **Step 6: App 给两处 ProfileForm 传 displayMode**

`frontend/src/App.tsx` 中 create 视图（225-231 行）与 edit 视图（233-243 行）的 `<ProfileForm ...>` 各加一个 prop `displayMode={displayMode}`。

- [ ] **Step 7: 构建 + 全部前端测试**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager/frontend && pnpm build && pnpm test`
Expected: 构建通过；全部测试 PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/LaunchButton.tsx frontend/src/components/LaunchButton.test.tsx frontend/src/components/ProfileForm.tsx frontend/src/App.tsx
git commit -m "feat(frontend): disable launch until kernel ready, hide clipboard toggle in native"
```

---

## Task 13: 关窗确认模态（React）+ pywebview 触发桥

**Files:**
- Create: `frontend/src/components/CloseModal.tsx`
- Modify: `frontend/src/App.tsx`（挂载模态 + 注册 `window.__cbShowCloseModal`）
- Create: `frontend/src/pywebview.d.ts`（类型声明）
- Test: `frontend/src/components/CloseModal.test.tsx`

**Interfaces:**
- Produces:
  - `CloseModal` — props `{ open: boolean; onChoice: (choice: "exit" | "tray" | "cancel", remember: boolean) => void }`
  - 全局 `window.__cbShowCloseModal?: () => void`（由 App 注册，桌面壳调用）
  - 选择通过 `window.pywebview?.api?.on_close_choice(choice, remember)` 回传

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/CloseModal.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CloseModal } from "./CloseModal";

describe("CloseModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<CloseModal open={false} onChoice={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("reports exit with remember flag", () => {
    const onChoice = vi.fn();
    render(<CloseModal open onChoice={onChoice} />);
    fireEvent.click(screen.getByLabelText(/remember/i));
    fireEvent.click(screen.getByRole("button", { name: /quit/i }));
    expect(onChoice).toHaveBeenCalledWith("exit", true);
  });

  it("reports tray without remember by default", () => {
    const onChoice = vi.fn();
    render(<CloseModal open onChoice={onChoice} />);
    fireEvent.click(screen.getByRole("button", { name: /tray/i }));
    expect(onChoice).toHaveBeenCalledWith("tray", false);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- CloseModal`
Expected: FAIL —模块不存在

- [ ] **Step 3: 写 CloseModal**

Create `frontend/src/components/CloseModal.tsx`:
```tsx
import { useState } from "react";

interface CloseModalProps {
  open: boolean;
  onChoice: (choice: "exit" | "tray" | "cancel", remember: boolean) => void;
}

export function CloseModal({ open, onChoice }: CloseModalProps) {
  const [remember, setRemember] = useState(false);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-1 border border-border rounded-lg p-6 w-80">
        <h2 className="text-sm font-semibold mb-2">Close CloakBrowser Manager?</h2>
        <p className="text-xs text-gray-400 mb-4">
          Browsers are still running. What should happen?
        </p>

        <label className="flex items-center gap-2 text-xs text-gray-300 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            className="rounded border-border bg-surface-2"
          />
          Remember my choice
        </label>

        <div className="flex flex-col gap-2">
          <button
            className="btn-danger"
            onClick={() => onChoice("exit", remember)}
          >
            Quit and close all browsers
          </button>
          <button
            className="btn-secondary"
            onClick={() => onChoice("tray", remember)}
          >
            Minimize to tray
          </button>
          <button
            className="btn-secondary"
            onClick={() => onChoice("cancel", false)}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `pnpm test -- CloseModal`
Expected: PASS

- [ ] **Step 5: 加 pywebview 类型声明**

Create `frontend/src/pywebview.d.ts`:
```typescript
export {};

declare global {
  interface Window {
    __cbShowCloseModal?: () => void;
    pywebview?: {
      api?: {
        on_close_choice?: (choice: string, remember: boolean) => void;
      };
    };
  }
}
```

- [ ] **Step 6: App 挂载模态并注册全局触发**

`frontend/src/App.tsx` 顶部 import 加：
```tsx
import { CloseModal } from "./components/CloseModal";
```
在 `AppContent` 内加 state 与注册 effect（放在其它 effect 附近）：
```tsx
  const [closeModalOpen, setCloseModalOpen] = useState(false);

  useEffect(() => {
    window.__cbShowCloseModal = () => setCloseModalOpen(true);
    return () => { delete window.__cbShowCloseModal; };
  }, []);

  const handleCloseChoice = useCallback(
    (choice: "exit" | "tray" | "cancel", remember: boolean) => {
      setCloseModalOpen(false);
      window.pywebview?.api?.on_close_choice?.(choice, remember);
    },
    [],
  );
```
在 `AppContent` 的最外层 `<div className="h-screen flex">`（154 行附近）内的末尾（`</div>` 前）挂载：
```tsx
      <CloseModal open={closeModalOpen} onChoice={handleCloseChoice} />
```

- [ ] **Step 7: 构建 + 全部前端测试**

Run: `pnpm build && pnpm test`
Expected: 构建通过；全部 PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CloseModal.tsx frontend/src/components/CloseModal.test.tsx frontend/src/pywebview.d.ts frontend/src/App.tsx
git commit -m "feat(frontend): add close-confirmation modal bridged to pywebview"
```

---

## Task 14: desktop/settings.py — 关窗偏好持久化

**Files:**
- Create: `desktop/__init__.py`（空）
- Create: `desktop/settings.py`
- Create: `desktop/tests/__init__.py`（空）
- Create: `desktop/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `load_settings() -> dict`（缺失/损坏时返回 `{"on_close": "ask"}`）
  - `save_settings(data: dict) -> None`（写 `get_data_dir()/settings.json`）

- [ ] **Step 1: 写失败测试**

Create `desktop/tests/test_settings.py`:
```python
"""Tests for desktop settings persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from desktop import settings


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    return tmp_path


def test_load_defaults_when_missing(data_dir):
    assert settings.load_settings() == {"on_close": "ask"}


def test_save_then_load_roundtrip(data_dir: Path):
    settings.save_settings({"on_close": "tray"})
    assert (data_dir / "settings.json").exists()
    assert settings.load_settings()["on_close"] == "tray"


def test_corrupt_file_falls_back_to_default(data_dir: Path):
    (data_dir / "settings.json").write_text("{not json", encoding="utf-8")
    assert settings.load_settings() == {"on_close": "ask"}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager && backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_settings.py -q`
Expected: FAIL —模块不存在

> 注：`desktop/` 需能 import `backend.config`。运行 pytest 时工作目录为仓库根，`backend` 与 `desktop` 均为顶层包，可直接 import。

- [ ] **Step 3: 写实现**

Create `desktop/__init__.py`（空文件）。
Create `desktop/tests/__init__.py`（空文件）。
Create `desktop/settings.py`:
```python
"""Persist the desktop client's close-behavior preference."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.config import get_data_dir

logger = logging.getLogger("cloakbrowser.desktop.settings")

_DEFAULTS = {"on_close": "ask"}


def _path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> dict:
    """Return persisted settings, falling back to defaults on any problem."""
    p = _path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULTS)
        merged = dict(_DEFAULTS)
        merged.update(data)
        if merged.get("on_close") not in ("ask", "exit", "tray"):
            merged["on_close"] = "ask"
        return merged
    except FileNotFoundError:
        return dict(_DEFAULTS)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("settings.json unreadable (%s); using defaults", exc)
        return dict(_DEFAULTS)


def save_settings(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 运行确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_settings.py -q`
Expected: PASS

- [ ] **Step 5: 让 pytest 收集 desktop/tests**

`pyproject.toml` 的 `testpaths` 加入 desktop：
```toml
[tool.pytest.ini_options]
testpaths = ["backend/tests", "desktop/tests"]
asyncio_mode = "auto"
```
Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: 后端 + desktop 测试全部 PASS

- [ ] **Step 6: Commit**

```bash
git add desktop/__init__.py desktop/settings.py desktop/tests/__init__.py desktop/tests/test_settings.py pyproject.toml
git commit -m "feat(desktop): add close-behavior settings persistence"
```

---

## Task 15: desktop/server.py — 后台 uvicorn 线程

**Files:**
- Create: `desktop/server.py`
- Create: `desktop/requirements.txt`
- Test: `desktop/tests/test_server.py`（仅测纯函数 `port_in_use`、`wait_for_server`；线程启动为手动验收）

**Interfaces:**
- Produces:
  - `port_in_use(port: int) -> bool`
  - `wait_for_server(url: str, timeout: float = 30.0) -> bool`
  - `class ServerHandle`：`start(port)`、`stop(timeout=10)`；内部持有 uvicorn `Server` 与线程

- [ ] **Step 1: 写失败测试（纯函数）**

Create `desktop/tests/test_server.py`:
```python
"""Tests for desktop server helpers (pure parts only)."""
from __future__ import annotations

import socket

from desktop import server


def test_port_in_use_false_for_free_port():
    # bind a socket to grab a free port, then release it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert server.port_in_use(free_port) is False


def test_port_in_use_true_when_listening():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert server.port_in_use(port) is True


def test_wait_for_server_times_out_fast():
    # nothing is listening on this URL; should return False within the timeout
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert server.wait_for_server(f"http://127.0.0.1:{port}/api/status", timeout=1.0) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_server.py -q`
Expected: FAIL —模块不存在

- [ ] **Step 3: 写实现**

Create `desktop/server.py`:
```python
"""Run the FastAPI backend in a background thread for the desktop client."""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
import urllib.request

logger = logging.getLogger("cloakbrowser.desktop.server")


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


class ServerHandle:
    def __init__(self) -> None:
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self, port: int) -> None:
        import uvicorn

        from backend.main import app

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            config = uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
            )
            self._server = uvicorn.Server(config)
            loop.run_until_complete(self._server.serve())

        self._thread = threading.Thread(target=run, daemon=True, name="uvicorn")
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal uvicorn to exit; its lifespan shutdown closes all browsers."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
```

Create `desktop/requirements.txt`:
```text
# Desktop client dependencies (Windows). Backend deps come from backend/requirements.txt.
pywebview>=5.0
pystray>=0.19
pillow>=10.0
pyinstaller>=6.0
```

- [ ] **Step 4: 运行确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_server.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/server.py desktop/requirements.txt desktop/tests/test_server.py
git commit -m "feat(desktop): add background uvicorn server handle + helpers"
```

---

## Task 16: desktop/controller.py + api_bridge.py — 关窗逻辑与 JS 桥

**Files:**
- Create: `desktop/controller.py`
- Create: `desktop/api_bridge.py`
- Test: `desktop/tests/test_controller.py`

**Interfaces:**
- Consumes: `settings.load_settings/save_settings`（Task 14）
- Produces:
  - `class Controller`：`on_closing() -> bool`、`on_close_choice(choice, remember)`；属性 `window`、`settings`、`server`、`_force_close`；方法 `running_count() -> int`
  - `class ApiBridge`：`on_close_choice(self, choice, remember)` 代理到 controller（暴露给 JS）

- [ ] **Step 1: 写失败测试**

Create `desktop/tests/test_controller.py`:
```python
"""Tests for desktop Controller close logic."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from desktop.controller import Controller


def _controller(monkeypatch, on_close="ask", running=0):
    monkeypatch.setattr("desktop.controller.load_settings", lambda: {"on_close": on_close})
    saved = {}
    monkeypatch.setattr("desktop.controller.save_settings", lambda d: saved.update(d))
    c = Controller(port=8977)
    c.window = MagicMock()
    monkeypatch.setattr(c, "running_count", lambda: running)
    return c, saved


def test_tray_pref_hides_and_cancels_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="tray")
    assert c.on_closing() is False
    c.window.hide.assert_called_once()


def test_exit_pref_allows_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="exit")
    assert c.on_closing() is True


def test_ask_no_browsers_allows_close(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="ask", running=0)
    assert c.on_closing() is True


def test_ask_with_browsers_shows_modal_and_cancels(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="ask", running=2)
    assert c.on_closing() is False
    c.window.evaluate_js.assert_called_once()


def test_choice_exit_remembers_and_forces_close(monkeypatch):
    c, saved = _controller(monkeypatch, on_close="ask", running=2)
    c.on_close_choice("exit", True)
    assert saved.get("on_close") == "exit"
    assert c._force_close is True
    c.window.destroy.assert_called_once()


def test_choice_tray_hides_without_remember(monkeypatch):
    c, saved = _controller(monkeypatch, on_close="ask", running=2)
    c.on_close_choice("tray", False)
    assert saved == {}
    c.window.hide.assert_called_once()


def test_force_close_bypasses_logic(monkeypatch):
    c, _ = _controller(monkeypatch, on_close="tray")
    c._force_close = True
    assert c.on_closing() is True
```

- [ ] **Step 2: 运行确认失败**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_controller.py -q`
Expected: FAIL —模块不存在

- [ ] **Step 3: 写 Controller**

Create `desktop/controller.py`:
```python
"""Owns the desktop window lifecycle and close-behavior decisions."""
from __future__ import annotations

import json
import logging
import urllib.request

from desktop.server import ServerHandle
from desktop.settings import load_settings, save_settings

logger = logging.getLogger("cloakbrowser.desktop.controller")


class Controller:
    def __init__(self, port: int) -> None:
        self.port = port
        self.window = None  # set by app.py after create_window
        self.server = ServerHandle()
        self.settings = load_settings()
        self._force_close = False

    def running_count(self) -> int:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/status", timeout=2
            ) as r:
                return int(json.loads(r.read()).get("running_count", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("running_count query failed: %s", exc)
            return 0

    def on_closing(self) -> bool:
        """pywebview 'closing' handler. Return True to allow close, False to cancel."""
        if self._force_close:
            return True
        choice = self.settings.get("on_close", "ask")
        if choice == "tray":
            self.window.hide()
            return False
        if choice == "exit":
            return True
        # "ask"
        if self.running_count() == 0:
            return True
        self.window.evaluate_js("window.__cbShowCloseModal && window.__cbShowCloseModal()")
        return False

    def on_close_choice(self, choice: str, remember: bool) -> None:
        """Called from the frontend (via ApiBridge) after the modal is answered."""
        if remember and choice in ("exit", "tray"):
            self.settings["on_close"] = choice
            save_settings(self.settings)
        if choice == "tray":
            self.window.hide()
        elif choice == "exit":
            self._force_close = True
            self.window.destroy()
        # "cancel": do nothing
```

- [ ] **Step 4: 写 ApiBridge**

Create `desktop/api_bridge.py`:
```python
"""JS-exposed API surface for the pywebview window."""
from __future__ import annotations

from desktop.controller import Controller


class ApiBridge:
    def __init__(self, controller: Controller) -> None:
        self._c = controller

    def on_close_choice(self, choice: str, remember: bool) -> None:
        self._c.on_close_choice(choice, remember)
```

- [ ] **Step 5: 运行确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_controller.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add desktop/controller.py desktop/api_bridge.py desktop/tests/test_controller.py
git commit -m "feat(desktop): add Controller close logic + JS API bridge"
```

---

## Task 17: desktop/tray.py — 系统托盘

**Files:**
- Create: `desktop/tray.py`
- Test: 手动（pystray 需 GUI 环境；仅做 import 冒烟）

**Interfaces:**
- Consumes: `Controller`（Task 16）、`settings.save_settings`
- Produces: `create_tray(controller) -> pystray.Icon`

- [ ] **Step 1: 写实现**

Create `desktop/tray.py`:
```python
"""System-tray icon for the desktop client."""
from __future__ import annotations

import logging

import pystray
from PIL import Image, ImageDraw

from desktop.settings import save_settings

logger = logging.getLogger("cloakbrowser.desktop.tray")


def _placeholder_icon() -> Image.Image:
    """A simple 64×64 icon. Replace desktop/assets/icon.png for a real one."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(37, 99, 235, 255))
    d.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 255))
    return img


def create_tray(controller) -> "pystray.Icon":
    def on_open(icon, item):
        if controller.window is not None:
            controller.window.show()

    def on_reset(icon, item):
        controller.settings["on_close"] = "ask"
        save_settings(controller.settings)

    def on_quit(icon, item):
        controller._force_close = True
        if controller.window is not None:
            controller.window.destroy()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Manager", on_open, default=True),
        pystray.MenuItem("Reset close behavior", on_reset),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("cloakbrowser", _placeholder_icon(), "CloakBrowser Manager", menu)
```

- [ ] **Step 2: import 冒烟（需先装 desktop 依赖）**

Run:
```bash
backend/.venv/Scripts/python.exe -m pip install -r desktop/requirements.txt
backend/.venv/Scripts/python.exe -c "import desktop.tray; print('ok')"
```
Expected: 打印 `ok`（确认 pystray / Pillow 可导入且模块语法正确）

- [ ] **Step 3: Commit**

```bash
git add desktop/tray.py
git commit -m "feat(desktop): add system tray icon"
```

---

## Task 18: desktop/app.py — 主入口接线

**Files:**
- Create: `desktop/app.py`
- Test: 手动验收（GUI）

**Interfaces:**
- Consumes: `server.port_in_use/wait_for_server`、`Controller`、`ApiBridge`、`create_tray`
- Produces: `main()` 入口；`python -m desktop.app` 可启动客户端

- [ ] **Step 1: 写实现**

Create `desktop/app.py`:
```python
"""Desktop client entry point: uvicorn + pywebview window + tray."""
from __future__ import annotations

import ctypes
import logging
import os
import threading

import webview

from desktop import server, tray
from desktop.api_bridge import ApiBridge
from desktop.controller import Controller

logger = logging.getLogger("cloakbrowser.desktop")


def _message_box(text: str, title: str = "CloakBrowser Manager") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        print(f"{title}: {text}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    # Native mode unless the user explicitly overrode it.
    os.environ.setdefault("USE_VNC", "0")
    port = int(os.environ.get("CLOAK_PORT", "8977"))

    if server.port_in_use(port):
        _message_box("CloakBrowser Manager is already running.")
        return

    controller = Controller(port)
    controller.server.start(port)

    if not server.wait_for_server(f"http://127.0.0.1:{port}/api/status", timeout=30):
        _message_box("Failed to start the backend server.")
        controller.server.stop()
        return

    bridge = ApiBridge(controller)
    window = webview.create_window(
        "CloakBrowser Manager",
        f"http://127.0.0.1:{port}",
        js_api=bridge,
        width=1280,
        height=800,
    )
    controller.window = window
    window.events.closing += controller.on_closing

    tray_icon = tray.create_tray(controller)
    threading.Thread(target=tray_icon.run, daemon=True, name="tray").start()

    webview.start()  # blocks until the window is destroyed

    # Window closed → tear down tray and backend (lifespan shutdown closes browsers)
    try:
        tray_icon.stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("tray stop failed: %s", exc)
    controller.server.stop(timeout=10)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 源码模式手动验收（Windows，需真实 cloakbrowser 二进制）**

前置：`cd frontend && pnpm build`（生成 `frontend/dist`，供后端静态服务）。
Run: `cd /d/Develop/Projects/CloakBrowser-Manager && backend/.venv/Scripts/python.exe -m desktop.app`
逐项确认：
1. 窗口打开，显示管理器 UI。
2. 若二进制未就绪，出现"Downloading browser kernel…"横幅且 Launch 禁用；下载完成后横幅消失、Launch 可用。
3. 新建 profile → Launch → **指纹浏览器窗口在桌面弹出**（非 VNC 画布）；主面板显示 RunningPanel（Running + "browser window is open on your desktop" + Copy CDP endpoint）。
4. 打开 `https://bot.sannysoft.com/` 之类检测页，确认正常渲染（真实 GPU）。
5. 直接关闭桌面浏览器窗口 → 3 秒内主面板切回编辑视图，profile 状态变 stopped。
6. 再次 Launch → 点顶部 Stop → 浏览器窗口关闭。
7. 有浏览器运行时点客户端窗口 X → 弹出 CloseModal（Quit / Minimize to tray / Cancel + Remember）。
   - Cancel：窗口保持。
   - Minimize to tray（不勾 Remember）：窗口隐藏，托盘图标在；托盘"Open Manager"可还原。
   - 勾 Remember + Quit：所有浏览器关闭、客户端退出、无残留进程（任务管理器确认无 chrome/uvicorn 残留）。
8. 重开客户端，有浏览器运行时点 X → 因已记住 exit，直接退出不弹窗；托盘"Reset close behavior"后恢复弹窗。

记录任何偏差为后续修复 issue。

- [ ] **Step 3: Commit**

```bash
git add desktop/app.py
git commit -m "feat(desktop): wire up app entry (server + pywebview + tray + close flow)"
```

---

## Task 19: 冻结资源解析核对

**Files:**
- 核对 `backend/config.py:frontend_dir()`（Task 2 已实现 frozen 分支）
- Create: `desktop/tests/test_frozen_paths.py`

**Interfaces:**
- Consumes: `config.frontend_dir()`

- [ ] **Step 1: 写测试覆盖 frozen 分支**

Create `desktop/tests/test_frozen_paths.py`:
```python
"""Verify frontend_dir resolves under a simulated PyInstaller freeze."""
from __future__ import annotations

import sys
from pathlib import Path

from backend import config


def test_frontend_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(tmp_path), raising=False)
    d = config.frontend_dir()
    assert d == Path(str(tmp_path)) / "frontend" / "dist"


def test_frontend_dir_source(monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    d = config.frontend_dir()
    assert d.parts[-2:] == ("frontend", "dist")
```

- [ ] **Step 2: 运行确认通过**

Run: `backend/.venv/Scripts/python.exe -m pytest desktop/tests/test_frozen_paths.py -q`
Expected: PASS（`frontend_dir()` 的 frozen 分支已在 Task 2 写好；若失败说明该分支有误，就地修 `backend/config.py`）

- [ ] **Step 3: Commit**

```bash
git add desktop/tests/test_frozen_paths.py
git commit -m "test(desktop): cover frozen frontend path resolution"
```

---

## Task 20: PyInstaller 打包 + 构建脚本 + 手动验收

**Files:**
- Create: `desktop/CloakBrowserManager.spec`
- Create: `desktop/build.md`（构建步骤文档）
- Modify: `.gitignore`（忽略 `build/`、`dist/`）

**Interfaces:**
- Consumes: 全部前述模块；`frontend/dist` 构建产物

- [ ] **Step 1: 写 PyInstaller spec**

Create `desktop/CloakBrowserManager.spec`:
```python
# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller desktop/CloakBrowserManager.spec  (run from repo root)
from PyInstaller.utils.hooks import collect_all

datas = [("frontend/dist", "frontend/dist")]
binaries = []
hiddenimports = ["backend.main", "desktop.app"]

# Bundle cloakbrowser + webview + pystray data/backends
for pkg in ("cloakbrowser", "webview", "pystray"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

block_cipher = None

a = Analysis(
    ["desktop/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CloakBrowserManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app, no console
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="CloakBrowserManager",
)
```

- [ ] **Step 2: 写构建文档**

Create `desktop/build.md`:
```markdown
# 构建 Windows 客户端

## 前置
- Windows 10/11 x64，已装 Edge WebView2 Runtime（Win11 自带）。
- Python 3.12（用 `backend/.venv`）。

## 步骤（在仓库根目录）
1. 装依赖：
   ```
   backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
   backend/.venv/Scripts/python.exe -m pip install -r desktop/requirements.txt
   ```
2. 构建前端（产物进 `frontend/dist`，会被打进包）：
   ```
   cd frontend && pnpm install && pnpm build && cd ..
   ```
3. 打包：
   ```
   backend/.venv/Scripts/pyinstaller.exe desktop/CloakBrowserManager.spec
   ```
4. 产物：`dist/CloakBrowserManager/CloakBrowserManager.exe`。

## 说明
- 浏览器内核**不打包**，首次运行由客户端从官方渠道下载（约 200MB），符合 CloakBrowser 二进制许可证。
- 数据目录默认 `%APPDATA%\CloakBrowser-Manager`（profiles、DB、settings.json）。
- 换图标：替换 `_placeholder_icon()`，或在 spec 的 `EXE(..., icon="desktop/assets/icon.ico")` 指定。
```

- [ ] **Step 3: 更新 .gitignore**

在 `.gitignore` 追加：
```
# PyInstaller
/build/
/dist/
*.spec.bak
```

- [ ] **Step 4: 执行打包（Windows 手动）**

按 `desktop/build.md` 执行。
Expected: 生成 `dist/CloakBrowserManager/CloakBrowserManager.exe`，无致命错误。

- [ ] **Step 5: 打包产物验收（Windows 手动）**

双击 `CloakBrowserManager.exe`，重跑 Task 18 Step 2 的验收清单第 1–8 项。额外确认：
1. 首次运行在干净机器（或删掉已下载内核后）触发内核下载横幅，完成后可 Launch。
2. 单实例：已运行时再双击 exe → 弹"already running"消息框后退出。
3. 数据目录落在 `%APPDATA%\CloakBrowser-Manager`。

- [ ] **Step 6: Docker/VNC 回归（不改行为的兜底核对）**

Run: `cd /d/Develop/Projects/CloakBrowser-Manager && docker compose up --build`
打开 `http://localhost:8080`，确认：`/api/status` 的 `display_mode` 为 `vnc`；Launch → noVNC 画面正常；剪贴板同步可用。
（容器内 `Xvnc` 存在 → `use_vnc()` 自动为真 → 行为与改造前一致。）

- [ ] **Step 7: Commit**

```bash
git add desktop/CloakBrowserManager.spec desktop/build.md .gitignore
git commit -m "build(desktop): add PyInstaller spec and build docs"
```

---

## Self-Review（计划自审结果）

**1. Spec 覆盖核对：**
- 模式判定（spec §3）→ Task 2。
- launch 原生分支：跳过 VNC / 无 DISPLAY / 去 swiftshader / `--window-size` / 可空 display（spec §4.1）→ Task 5。
- 停止清理、剪贴板 501、CDP 不变、数据目录、API 变化（spec §4.2）→ Task 3/5/6。
- 内核下载（spec §4.2、§7）→ Task 7/8。
- 前端模式分流、RunningPanel、ProfileForm、内核横幅、关窗模态（spec §5）→ Task 9–13。
- 桌面壳单实例/USE_VNC/uvicorn 线程/关窗拦截/托盘/退出清理/settings.json（spec §6）→ Task 14–18。
- PyInstaller onedir、资源路径、内核不打包（spec §7）→ Task 19/20。
- 错误处理（spec §8）→ 分散在 Task 6（launch 500 保留）、8（下载失败）、11（横幅+重试）、16（退出超时）、18（单实例消息框）。
- 测试（spec §9）→ 各 Task 的 pytest/vitest + Task 18/20 手动验收 + Task 20 Docker 回归。
- 范围外（spec §10）→ 未安排任何 macOS/Linux 打包、自动更新、签名、下载百分比任务。
- 预检（spec §11）→ Task 1。

**2. 占位符扫描：** 无 TBD/TODO/“类似 Task N”。所有代码步骤均含完整代码；Task 1/18/20 的手动步骤含具体命令与逐条验收项。

**3. 类型一致性核对：**
- `use_vnc()`/`display_mode()`/`get_data_dir()`/`frontend_dir()` 在 Task 2 定义，Task 3/5/6/19 一致引用。
- `RunningProfile.display/ws_port: int | None` 在 Task 5 统一。
- `BinaryManager` 的 `ready/downloading/error/status()/start()/wait_ready()` 在 Task 7 定义，Task 8 一致引用。
- 前端 `display_mode`、`BinaryStatus`、`getBinaryStatus/downloadBinary` 在 Task 9 定义，Task 11 引用一致。
- `LaunchButton.canLaunch`、`ProfileForm.displayMode` 在 Task 12 定义，Task 11/12 调用点一致。
- `Controller.on_closing/on_close_choice`、`ApiBridge.on_close_choice`、`window.__cbShowCloseModal`、`window.pywebview.api.on_close_choice` 在 Task 13/16 两侧签名一致。
- `ServerHandle.start/stop`、`port_in_use`、`wait_for_server` 在 Task 15 定义，Task 18 引用一致。

**已知外部不确定性（已在计划内消化）：** `no_viewport` 支持性、内核就绪查询 API、pywebview/pystray 跨线程行为 —— 前两者由 Task 1 预检并在 Task 5/7 留有回退注释；GUI 行为由 Task 18/20 手动验收兜底。
