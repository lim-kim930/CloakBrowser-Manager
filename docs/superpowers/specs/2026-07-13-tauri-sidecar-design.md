# 设计方案：Tauri + Python Sidecar 桌面客户端改造

**日期**：2026-07-13
**分支**：`feature/tauri-desktop-client`
**状态**：设计已确认，待落实施计划
**取代**：`implementation_plan.md`（本文档正式化并大幅细化后，该文件删除）

---

## 1. 背景与目标

CloakBrowser Manager 当前是 Docker + VNC 的 Web 应用：一个 FastAPI 进程同时伺服 REST API、React 静态包、以及两条 WebSocket 代理（VNC 与 CDP）。每个 profile 在容器内启动 Xvnc（KasmVNC）虚拟显示器，CloakBrowser Chromium 通过 `DISPLAY=:N` 渲染到该虚拟屏，用户经 noVNC 在浏览器里"隔窗"操作。

**改造目标**：变成跨平台的轻量级桌面客户端。

- **Tauri**（Rust 壳）打包现有 React 前端为桌面应用。
- **PyInstaller** 把现有 FastAPI 后端编译为可执行程序，Tauri 作为 **sidecar** 拉起。
- **彻底移除 VNC**：启动的浏览器是用户桌面上的**真实窗口**，不再需要虚拟显示器和画面串流。UI 只显示"运行中"状态和"停止"按钮。
- 数据从硬编码 `/data` 迁到 OS 标准应用数据目录。
- 关闭应用时，Python sidecar 和它拉起的所有 Chromium 进程一并清理。

### 1.1 目标平台（v1）

**Windows 优先**（当前开发机），架构预留跨平台：代码层用 `platformdirs`、target-triple 命名、平台分支等写法，使 macOS/Linux 的构建与验证可在后续补齐而无需重构。

### 1.2 硬约束（继承自 CLAUDE.md）

- **绝不把 CloakBrowser Chromium 二进制打进任何分发物**（`BINARY-LICENSE.md` 禁止再分发）。首次运行时由 `cloakbrowser` 现场下载。
- Conventional Commits，一个逻辑任务一个 commit。

---

## 2. 关键决策摘要（brainstorming 结论）

| 决策点 | 结论 |
|---|---|
| v1 目标平台 | Windows 优先，架构预留跨平台 |
| CDP 反向代理 | **保留**（自动化工具经固定 URL 接入，端口轮换对外透明） |
| AUTH_TOKEN 认证 | **移除登录页与中间件**，代之以轻量 Origin 防护 |
| sidecar 生命周期 | **方案 A：Rust 托管**（setup 钩子拉起/监管/退出钩子清理） |
| Docker 相关文件 | **全部删除**（Dockerfile、docker-compose.yml、entrypoint.sh） |
| 后端语言 | **保留 Python sidecar**（见 §13 的调查依据，不做 Rust 重写） |

---

## 3. 架构总览

### 3.1 进程模型

```
Tauri 主进程 (Rust)
 ├─ WebView 窗口 (React UI，Tauri 打包，origin: http://tauri.localhost / tauri://localhost)
 └─ sidecar: server(.exe) (PyInstaller 冻结的 FastAPI，绑定 127.0.0.1:{port})
     └─ Playwright node driver
         └─ CloakBrowser Chromium × N (用户桌面上的真实窗口)
```

### 3.2 通信通道

- **前端 → 后端**：`http://127.0.0.1:{port}/api/*`。这是跨 origin 请求（WebView 的 origin 不是 `127.0.0.1:{port}`），因此后端必须配置 CORS。
- **前端 ↔ Rust**：Tauri IPC —— Rust `#[tauri::command]`（端口探测、写配置）+ 事件（`backend-ready` / `port-conflict` / `backend-error`）。
- **外部自动化工具 → 后端**：CDP 反向代理 `/api/profiles/{id}/cdp`（保留现状，供 Playwright/Puppeteer `connect_over_cdp`）。

---

## 4. 生命周期

### 4.1 启动时序

1. **单实例**：启用 Tauri single-instance 插件，二次启动只聚焦已有窗口（避免两个壳争抢同一端口/sidecar）。
2. **读配置**：Rust 从 Tauri `app_config_dir`（按 identifier，如 `%APPDATA%\com.cloakbrowser.manager\config.json`）读取上次保存的端口，默认 **8000**。
3. **端口探测**：Rust 对 `127.0.0.1:{port}` 做 TCP 连接尝试。
   - **空闲** → 进入 4。
   - **被占** → 发 `port-conflict` 事件；前端渲染 `PortConfigModal`，阻断应用；用户输入新端口 → Rust command 复测 → 通过则写回 config.json 并进入 4。
4. **拉起 sidecar**：Rust `Command.sidecar("server", ["--port", port, "--data-dir", <app_data_dir>])`，**保持 stdin 为管道**（用于关闭看门狗，见 §4.3）。
5. **等待就绪**：Rust 轮询 `GET http://127.0.0.1:{port}/api/health`，直到 200（超时 30s；超时发 `backend-error`）。
6. **内核检查**：后端启动时在后台线程执行 `ensure_binary()`；`/api/health` 的 `binary.state` 反映 `downloading` / `ready` / `error`。
7. **前端渲染**：
   - `binary.state == downloading` → "正在下载浏览器内核…" 界面（health 轮询）。
   - `binary.state == ready` → 主界面（现有 `AppContent`）。
   - `backend-error` → 错误界面 + 重试按钮（重试 = 重新触发 Rust 拉起流程）。

### 4.2 端口冲突流程（前端状态机）

前端在 `AppContent` 外包一层 **bootstrap 状态机**：

```
detecting → (非 Tauri) ────────────────► ready(相对路径, 走 Vite 代理)
    │
    └ (Tauri) → 监听事件
                ├ port-conflict  → PortConfigModal → (复测通过) → waiting-backend
                ├ backend-ready  → waiting-binary
                │                    ├ downloading → DownloadingScreen(轮询 health)
                │                    └ ready       → ready(AppContent)
                └ backend-error  → ErrorScreen(重试)
```

**非 Tauri 环境**（纯 `pnpm dev`）由 bootstrap 自动识别（`window.__TAURI_INTERNALS__` 不存在）并整条跳过，`api` baseUrl 用相对路径走 Vite 代理，保持纯 Web 开发循环可用。

### 4.3 关闭时序（三层保险）

1. **正常退出**：窗口关闭 → Rust `RunEvent::ExitRequested` 钩子 → `POST /api/shutdown` → 后端置 `uvicorn.Server.should_exit = True` → lifespan 收尾调用 `browser_mgr.cleanup_all()`，逐个 `context.close()`（**会话数据完整落盘**）→ 进程退出。Rust 等待 sidecar 退出，最多约 10s，超时 `child.kill()` 硬杀。
2. **Tauri 崩溃 / 被任务管理器杀**：sidecar 的 **stdin 看门狗线程**检测到 stdin EOF（父进程管道断开）→ 触发同一条优雅关闭路径。
3. **Python 被硬杀**：Playwright node driver 检测到与父进程管道断开 → 自动杀掉它拉起的所有 Chromium（Playwright 内建行为，最后兜底）。

> 单个 Chromium 被用户手动关闭的情况：`context.on("close")` 回调（已存在）回收该 profile 状态；前端 3s 轮询同步 UI。

---

## 5. 安全模型（替代 AUTH_TOKEN）

后端只绑 `127.0.0.1`。删除 `AuthMiddleware`、三个 `/api/auth/*` 端点、cookie 逻辑、`LoginPage`。代之以 **`OriginCheckMiddleware`**：

- **规则**：对**状态变更请求（POST/PUT/DELETE）和 WebSocket 升级**，若请求**带 `Origin` 头且不在白名单** → **403**。
- **白名单**：`http://tauri.localhost`、`tauri://localhost`（Tauri WebView 的 origin，Windows 上为前者）、`http://localhost:5173`、`http://127.0.0.1:5173`（dev）。白名单可经 `--allow-origin` 参数追加。
- **放行**：无 `Origin` 头的请求（Rust 健康轮询、外部 CDP 自动化工具、curl）不受影响；GET 请求不拦截（只读，且 CORS 已限制浏览器跨站读取响应）。
- **目的**：防止用户浏览器里的恶意网页对本地端口发起写操作 / DNS rebinding。

`CORSMiddleware` 同时配置，`allow_origins` 用同一份白名单，`allow_credentials=False`。

---

## 6. 数据与路径

### 6.1 应用数据目录

- **后端数据**（profiles.db + profiles/<id>/）：默认 `platformdirs.user_data_dir("CloakBrowser")`
  - Windows：`%LOCALAPPDATA%\CloakBrowser`
  - macOS：`~/Library/Application Support/CloakBrowser`
  - Linux：`~/.local/share/CloakBrowser`
  - 可经 `--data-dir` 覆盖（测试 / 开发 / 便携模式）。
- **Tauri 壳配置**（端口号 config.json）：Tauri `app_config_dir`（按 identifier）。
- **Chromium 内核缓存**：设置环境变量 `CLOAKBROWSER_CACHE_DIR = <app_data_dir>/chromium-cache`，把内核缓存收拢到应用数据目录内（默认是 `~/.cloakbrowser/`），便于管理和"清理缓存"功能。

### 6.2 数据迁移

Docker 时代的 `/data` **不迁移**，桌面版全新开始（容器与桌面的数据目录语义不同，且无既有桌面用户）。

---

## 7. 后端改造

### 7.1 `backend/main.py`（收缩约一半）

**删除**：
- VNC WebSocket 代理 + 全部 RFB 协议处理函数（`_parse_kasmvnc_clipboard`、`_build_server_cut_text`、`_rfb_*`、`_filter_rfb_client_messages`、`_rewrite_*`、`vnc_proxy` 等，约 450 行）。
- clipboard 两个端点（`set_clipboard` / `get_clipboard`）及 `_xclip_procs`。
- `AuthMiddleware`、`_check_auth`、`_is_https`、三个 `/api/auth/*` 端点。
- 静态前端伺服（`FRONTEND_DIR` 挂载、`/assets`、`serve_spa` SPA fallback）—— 前端由 Tauri 打包。

**新增**：
- `OriginCheckMiddleware`（§5）+ `CORSMiddleware`。
- `GET /api/health` → `{"status": "ok", "version": <manager ver>, "binary": {"state": "ready|downloading|error", "version": <chromium ver>, "error": <str|null>}}`。
- `POST /api/shutdown` → 置 `server.should_exit = True`，返回 `{"ok": true}`。仅接受来自本机、经 Origin 检查的请求。
- `__main__` 入口 + `argparse`：`--port`（默认 8000）、`--host`（默认 127.0.0.1）、`--data-dir`（可选）、`--allow-origin`（可重复，可选）。
- 程序化构造 `uvicorn.Config` + `uvicorn.Server`，**保留 server 实例引用**供 shutdown 端点使用（不能用 `uvicorn.run()`，那样拿不到实例）。
- **stdin 看门狗线程**：读 stdin 到 EOF → 触发优雅关闭（`server.should_exit = True`）。仅在冻结/sidecar 模式启用（有 `--port` 参数即认为是 sidecar 模式）。

**保留**：profiles CRUD、launch/stop/status、`/api/status`、CDP 全套代理（`cdp_info`、`cdp_json_version`、`cdp_json_list`、`cdp_proxy`、`cdp_page_proxy`、`_proxy_cdp_websocket`）。

### 7.2 `backend/browser_manager.py`

**删除**：
- `from .vnc_manager import VNCManager`、`self.vnc`、所有 `vnc.allocate/start_vnc/stop_vnc/cleanup_*` 调用。
- launch 中的 `env={..., "DISPLAY": ...}`。
- `_build_fingerprint_args` 里的 `--use-angle=swiftshader`（VNC 软件渲染用；桌面有真实 GPU；且 cloakbrowser 默认参数不含它）。
- clipboard init script 注入（`_clipboard_init_js` 及注入循环）。
- `RunningProfile` 的 `display`、`ws_port` 字段。

**变更**：
- **视口策略**：删除 `viewport={"width": ..., "height": ... - 133}`。headed 模式**不传 viewport 参数**，让 cloakbrowser 默认走 `no_viewport`（源码验证：headed 下屏幕尺寸取真实显示器，额外叠加 viewport 会破坏 `outerWidth >= innerWidth` 一致性，是 bot 特征）。指纹的 `--fingerprint-screen-width/height` 参数照常传。
- **launch 前置内核检查**：内核未就绪时抛 `RuntimeError`，API 层转 503（见 §7.4）。
- `_on_browser_closed` / `stop` / `cleanup_all` 去掉 VNC 收尾，只保留 `context.close()`。

**保留**：CDP 端口轮换（`_allocate_cdp_port`，Windows 同样有 TIME_WAIT）、`_build_fingerprint_args` 其余部分、`_normalize_proxy` / `_validate_proxy`、Singleton 锁清理（`SingletonLock/Cookie/Socket`，Windows 崩溃后同样残留）、`_init_profile_defaults`（默认书签/DuckDuckGo）、`auto_launch_all`、`context.on("close")` 回调。

**launch 环境变量**：注入 `CLOAKBROWSER_CACHE_DIR`（§6.1）到子进程 env（或进程级 `os.environ`，在入口设置一次）。

### 7.3 `backend/database.py`

- `DATA_DIR` 从硬编码 `Path("/data")` 改为**由入口注入**：新增 `configure(data_dir: Path)` 或模块级可变，入口按 `--data-dir` 或 `platformdirs` 设置后再 `init_db()`。
- `DB_PATH` 随之派生。
- schema 不变。`clipboard_sync` 列**保留在库中**（避免破坏性迁移），但从 API 模型与 UI 移除。

### 7.4 API 层内核未就绪处理

`POST /api/profiles/{id}/launch`：捕获内核未就绪异常 → `HTTPException(503, "Browser core not ready")`。前端 launch 失败时提示"内核仍在下载"。`auto_launch_all` 在内核就绪后再执行（启动时若 `downloading` 则等待 `ready` 再跑）。

### 7.5 `backend/models.py`

- `ProfileResponse` / `ProfileStatusResponse` / `LaunchResponse`：删 `vnc_ws_port`、`display`。
- 删 `LoginRequest`、`ClipboardRequest`。
- `clipboard_sync` 从 `ProfileCreate` / `ProfileUpdate` / `ProfileResponse` 移除。
- 新增 `HealthResponse`（§7.1 结构）。

### 7.6 删除文件

`backend/vnc_manager.py`、`backend/tests/test_vnc_manager.py`、`backend/tests/test_rfb.py`。

### 7.7 `backend/requirements.txt`

- 新增 `platformdirs`。
- 保留 `websockets`、`httpx`（CDP 代理仍用）。
- `cloakbrowser[geoip]`、`fastapi`、`uvicorn[standard]`、`pydantic` 不变。

---

## 8. 前端改造

### 8.1 新增 bootstrap 层

新文件 `frontend/src/bootstrap/`：
- `useBootstrap.ts`：§4.2 状态机，监听 Tauri 事件，管理 `detecting/port-conflict/waiting-backend/downloading-binary/ready/backend-error`。
- `PortConfigModal.tsx`：端口冲突输入 + Rust command 复测。
- `DownloadingScreen.tsx`：内核下载中提示（轮询 `/api/health`）。
- `BackendErrorScreen.tsx`：错误 + 重试。
- `tauri.ts`：封装 `isTauri()`、事件订阅、command 调用（依赖 `@tauri-apps/api`）。

`App.tsx`：在现有 auth 分支**之前**加 bootstrap gate；auth 相关分支（`authState`、`LoginPage`）整体删除，`AppContent` 的 `authRequired` / `onLogout` 参数移除。

### 8.2 `frontend/src/lib/api.ts`

- 新增 `setApiBase(url: string)` 与内部 `_base`；`request()` 用 `_base + path`。
- Tauri 模式：`backend-ready` 后 `setApiBase("http://127.0.0.1:" + port)`。
- dev 模式：`_base = ""`（相对路径，走 Vite 代理）。
- 类型同步 §7.5：`Profile` / `LaunchResult` 删 `vnc_ws_port`；`Profile` 删 `clipboard_sync`。
- 删 `authStatus` / `login` / `logout`。
- 新增 `health()`。

### 8.3 删除

- `frontend/src/components/ProfileViewer.tsx`、`frontend/src/novnc.d.ts`、`frontend/src/components/LoginPage.tsx`。
- `App.tsx` 的 `view === "view"` VNC 分支、`handleVncDisconnect`。
- `ProfileForm.tsx` 的 `clipboard_sync` 开关。
- 依赖 `@novnc/novnc`。

### 8.4 运行态 UI

- 选中运行中的 profile 仍显示 `ProfileForm`（顶部已有运行标识 + `LaunchButton` 的停止按钮，足够）。删除原"点开进 VNC 页"的 `view` 状态跳转。
- `ProfileForm` 顶部新增 **CDP 地址复制按钮**：运行中时显示，点击复制 `http://127.0.0.1:{port}/api/profiles/{id}/cdp`，方便自动化用户 `connect_over_cdp`。
- `useProfiles` 的 3s 轮询保留（用户直接关 Chromium 窗口时靠它回收 UI 状态）。

### 8.5 新依赖

`@tauri-apps/api`（event + core invoke）。

---

## 9. Tauri 工程（Rust 侧）

- 位置：`frontend/src-tauri/`，**Tauri v2**，identifier `com.cloakbrowser.manager`。
- `tauri.conf.json`：
  - `bundle.externalBin: ["bin/server"]`（Tauri 按 target-triple 匹配 `bin/server-x86_64-pc-windows-msvc.exe`）。
  - 插件：`tauri-plugin-single-instance`。
  - `frontendDist` 指向 `../dist`；`devUrl` 指向 Vite。
  - capabilities 最小化（自定义 command + event）。
- Rust 代码（约 200 行，`src-tauri/src/`）：
  - 配置读写（`config.json` 端口）。
  - `#[tauri::command] probe_port(port) -> bool`（TCP 探测）。
  - `#[tauri::command] save_port(port)`。
  - sidecar spawn + 监管：**debug 构建 spawn `python -m backend.main`（源码模式），release 构建 spawn sidecar 二进制**（`tauri::generate_context` + `cfg!(debug_assertions)` 分支）——`tauri dev` 无需每次先跑 PyInstaller。
  - 健康轮询 → 发 `backend-ready` / `backend-error`。
  - `RunEvent::ExitRequested` 钩子：`POST /api/shutdown` → 等待 → 超时 `kill`。
  - 持有 sidecar `CommandChild`，stdin 保持打开。

---

## 10. 打包（PyInstaller sidecar）

新文件 `backend/build.py`：
- 调 PyInstaller，`--name server`。
- **v1 采用 `--onefile`**（干净匹配 Tauri sidecar 单文件模型）；文档记录 onedir 作为逃生口（若冷启动慢 / 杀软误报严重则切换，onedir 需把整目录作为 Tauri resources 打包）。
- 关键收集项：
  - `--collect-all cloakbrowser`（含 geoip 数据、配置里的签名公钥）。
  - `--collect-all playwright`（**node driver，最容易漏**）。
  - Ed25519 验签依赖：cloakbrowser 下载时验签，须确保其 crypto 依赖（`cryptography` 或 `pynacl`）被收集（`--collect-all` 覆盖或显式 `--hidden-import`）。
  - uvicorn 隐式导入（`uvicorn.logging`、loop/protocol 子模块）。
- **不打包 Chromium 内核**（BINARY-LICENSE）。运行时 `ensure_binary()` 下载。
- 自动检测 target triple（`rustc -Vv` 解析 host，或平台推导），产物复制到 `frontend/src-tauri/bin/server-<triple>{ext}`。
- **冻结模式验证项**：确认 `CLOAKBROWSER_CACHE_DIR` 生效、内核下载缓存落在应用数据目录而非 onefile 的临时解压目录（`sys._MEIPASS`）。

---

## 11. 开发工作流（三档）

1. **纯 Web**（迭代 UI/API 最快）：
   `python -m uvicorn backend.main:app --reload --port 8000` + `pnpm dev`（Vite 代理改指 8000）。bootstrap 自动跳过。
2. **`pnpm tauri dev`**：验证 IPC、bootstrap、端口冲突流程；Rust 走源码模式 spawn Python。
3. **`pnpm tauri build`**：先 `python backend/build.py` 再 Tauri 打包；验证真实 sidecar 与三层清理。

> 注意：`backend/main.py` 用相对导入，必须以包方式 `python -m backend.main` 运行（不能 `cd backend`）。

---

## 12. 测试策略

### 12.1 后端（pytest）

- 保留 `conftest.py` 的 cloakbrowser mock；`tmp_db` fixture 改用新的 `--data-dir` 注入路径。
- **删除**：`test_vnc_manager.py`、`test_rfb.py`；`test_auth.py`（auth 移除）；`test_api.py` 中 clipboard / VNC 相关用例。
- **新增**：
  - `GET /api/health`（三种 binary state）。
  - `OriginCheckMiddleware`：带白名单 Origin 的写请求放行、带非白名单 Origin 的写请求 403、无 Origin 放行、GET 不拦截、WS 升级检查。
  - launch 在内核未就绪时返回 503。
  - argparse / 入口参数解析（`--port` / `--data-dir` / `--allow-origin`）。
  - `POST /api/shutdown` 置位（mock server）。
- 适配：`test_models.py`、`test_browser_manager.py`（去 VNC/display 字段、viewport 变更）。

### 12.2 前端（vitest）

- `api.test.ts` 适配 baseUrl 机制。
- 新增 bootstrap 状态机测试（mock `@tauri-apps/api` 的 event/invoke）：非 Tauri 跳过、port-conflict → modal、downloading → screen、error → retry。
- `useProfiles.test.ts` 基本不动（删 clipboard_sync 相关断言）。

### 12.3 Rust

- 端口探测函数单元测试。
- spawn/kill/退出钩子属手动验证（§14）。

---

## 13. cloakbrowser 集成注意事项（源码调查所得，v0.4.10）

> 这些事实是"保留 Python"决策的依据，也是实现时的约束。

- **定位**：`cloakbrowser` 是 "drop-in Playwright replacement"。反指纹**编译在 Chromium 二进制里**，靠 flag 激活；Python 包是官方 SDK 封装。所有 launch 路径**强制经 Playwright**（`pw.chromium.launch_persistent_context(executable_path=binary, ...)`），无直接 subprocess 路径。
- **二进制下载**（`download.py`，~1160 行）：从 `https://cloakbrowser.dev/chromium-v{version}/...`（GitHub Releases 兜底）下载，**Ed25519 验签** SHA256SUMS 清单（公钥钉在 `config.py`），校验哈希，缓存到 `~/.cloakbrowser/`（可经 `CLOAKBROWSER_CACHE_DIR` 覆盖），有版本 marker 与自动更新。
- **版本门控行为**（`config.py`）：`HEADLESS_NO_VIEWPORT_MIN_VERSION`、`binary_supports_maximized_window` 等——**哪个二进制版本支持哪种一致窗口行为是包里的知识**。这类逻辑是"静默失败"风险来源，不宜自行复刻。
- **headed viewport**：headed 自动 `no_viewport`，屏幕取真实显示器；**不要叠加 viewport**（背书 §7.2 的视口变更）。
- **有用的环境变量**（实现时利用）：
  - `CLOAKBROWSER_CACHE_DIR`：内核缓存目录 → 收拢到应用数据目录。
  - `CLOAKBROWSER_BINARY_PATH`：指向本地二进制、跳过下载 → **dev / CI / 测试**加速。
  - `CLOAKBROWSER_VERSION`：钉版本。
  - `CLOAKBROWSER_DOWNLOAD_URL`：覆盖下载源。
- **API 面**：`ensure_binary()`（缺失则下载，阻塞式 → 放后台线程）、`binary_info()`（查本地状态，供 health）、`check_for_update()`、`clear_cache()`。

---

## 14. 验证计划（手动）

继承原文档 5 条 + 桌面特有项：

1. 无 Docker 环境下，前后端能分别独立构建（`build.py` 产出 sidecar，`pnpm build` 产出 dist）。
2. 启动打包后的 Tauri App，前端能拉起后台 Python server 并转入主界面。
3. 首次运行：内核不存在时显示下载界面，下载完成后转主界面（用干净的 `CLOAKBROWSER_CACHE_DIR` 复现）。
4. 用其他程序占用 8000 端口，App 弹出 `PortConfigModal`，改端口后正常启动。
5. 创建 profile 并启动，桌面**原生弹出 Chromium 窗口**，代理与指纹生效（打开书签栏里的检测站验证）。
6. CDP 复制按钮拿到的 URL 能被外部 Playwright `connect_over_cdp` 连上。
7. **三层清理**：
   - 正常关闭 App → Python 与所有 Chromium 退出（任务管理器确认无残留）。
   - 任务管理器杀 Tauri → sidecar 经 stdin 看门狗自退，Chromium 随之关闭。
   - 杀 sidecar → 前端显示 `BackendErrorScreen`，可重试。

---

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| PyInstaller 漏收 Playwright node driver → 运行时找不到 driver | `--collect-all playwright`；构建后冒烟测试真实 launch |
| onefile 冷启动慢 / 杀软误报 | v1 接受；文档记录 onedir 逃生口 |
| 冻结模式下内核缓存落到 `_MEIPASS` 临时目录（重启即丢） | 显式设 `CLOAKBROWSER_CACHE_DIR` 到应用数据目录并验证 |
| Ed25519 验签依赖未被收集 → 下载失败 | 显式收集 crypto 依赖；离线/首启验证 |
| Tauri WebView origin 与白名单不符 → CORS/Origin 拦截自身请求 | 实测 Windows WebView2 的实际 origin，校准白名单 |
| 关闭时 Chromium 未落盘会话 | 走 `context.close()` 优雅路径 + Rust 等待窗口，不直接硬杀 sidecar |

## 16. 未决（实现时确认，不阻塞设计）

- Windows WebView2 的确切 origin 字符串（`http://tauri.localhost` 待实测校准）。
- onefile vs onedir 的最终取舍（先 onefile，视冒烟结果定）。
- `ensure_binary()` 的确切阻塞时长与进度回调能力（决定下载界面是否能显示百分比，还是仅 spinner）。

---

## 17. 里程碑分解（供 writing-plans 阶段展开）

1. **后端解耦**：删 VNC/auth/clipboard/静态伺服；加 argparse 入口 + health + shutdown + Origin/CORS 中间件；database 路径注入；models 收敛。测试绿。
2. **browser_manager 桌面化**：去 VNC/DISPLAY/swiftshader/viewport hack；内核就绪检查；cache dir 环境变量。测试绿。
3. **PyInstaller `build.py`**：产出 sidecar，冒烟真实 launch（用 `CLOAKBROWSER_BINARY_PATH` 或真下载）。
4. **Tauri 工程 + Rust 托管**：init、externalBin、single-instance、探测/spawn/健康/退出钩子、stdin 看门狗对接。
5. **前端 bootstrap**：状态机、PortConfigModal、下载/错误界面、api baseUrl、删 VNC/login 组件、CDP 复制按钮。
6. **清理与文档**：删 Docker 三件套、README 重写、CLAUDE.md 同步、`.gitignore`（`src-tauri/target`、`src-tauri/bin`、PyInstaller `build/`、`dist/`、`*.spec`）、删 `implementation_plan.md`。
7. **端到端验证**：§14 全过。
