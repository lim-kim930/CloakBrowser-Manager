# 设计：原生桌面模式 + Windows 客户端打包

- **日期**：2026-07-11
- **状态**：已获用户逐节确认，待书面审阅
- **范围**：CloakBrowser-Manager 双模式改造（VNC / 原生）与 Windows 桌面客户端

## 1. 背景与目标

CloakBrowser-Manager 目前只支持 Docker + VNC 部署：每个 profile 在容器内的虚拟显示器（KasmVNC/Xvnc）上启动 CloakBrowser，前端通过 noVNC WebSocket 代理查看和操作浏览器画面。

目标：

1. **原生模式**——在 Windows 上点击 Launch 后，指纹浏览器窗口直接出现在用户桌面上，不经过 VNC。
2. **桌面客户端**——将管理器打包为一个 Windows 客户端应用（独立窗口，双击即用）。
3. **双模式共存**——现有 Docker + VNC 远程模式完整保留，便于跟进上游更新。

## 2. 已确认的决策

| 决策点 | 结论 |
|--------|------|
| 目标平台 | 仅 Windows（x64） |
| VNC 模式去留 | 保留，双模式共存 |
| 客户端技术 | pywebview（Edge WebView2）+ PyInstaller |
| 分发范围 | 自己/小范围使用，不需要代码签名 |
| 运行中的界面 | 简洁状态面板（RunningPanel） |
| 关闭窗口行为 | 弹对话框让用户选择（退出全部 / 最小化到托盘），带"记住我的选择" |
| 模式判定依据 | 以"是否使用 VNC"区分，**不以操作系统区分** |

可行性已确认：CloakBrowser 官方 GitHub Releases 提供 `cloakbrowser-windows-x64.zip` 二进制。

## 3. 模式判定

新增环境变量 `USE_VNC`，判定逻辑集中在 `backend/config.py` 的 `use_vnc()` 函数，进程启动时确定一次，全局只读：

| `USE_VNC` 取值 | 行为 |
|----------------|------|
| `1` / `true` | VNC 模式（现有行为） |
| `0` / `false` | 原生模式 |
| 未设置 | 自动探测：`shutil.which("Xvnc")` 找得到 → VNC 模式；找不到 → 原生模式 |

效果：Docker 镜像（内置 KasmVNC）零配置进 VNC 模式，行为不变；Windows 桌面（无 Xvnc）自动进原生模式；显式设置永远优先。

## 4. 后端改动

### 4.1 `BrowserManager.launch()` 分支点（原生模式）

1. 跳过 `vnc.allocate()` / `start_vnc()`，不创建虚拟显示器。
2. 不传 `DISPLAY` 环境变量，浏览器窗口直接出现在当前桌面。
3. 去掉 `--use-angle=swiftshader`，使用真实 GPU（`--fingerprint-gpu-vendor/renderer` 伪装参数照常生效）。
4. 不强制 viewport（VNC 模式的 `height - 133` hack 仅保留在 VNC 分支）；改传 `--window-size=W,H` 使窗口初始尺寸匹配 profile 屏幕设置；`--fingerprint-screen-width/height` 不变。
5. `RunningProfile.display` / `ws_port` 字段改为可选，原生模式下为 `None`。

### 4.2 其他后端改动

- **停止/崩溃清理**：`context.on("close")` 回调逻辑不变；原生模式下无 Xvnc 需要清理，跳过即可。用户直接关闭浏览器窗口 → 状态自动变 `stopped`。
- **剪贴板端点**（基于 xclip 的 GET/POST `/clipboard`）：原生模式返回 `501 Not Implemented`；原生窗口天然使用系统剪贴板。
- **CDP 自动化**：不变。原生模式同样分配 `cdp_port`，`/api/profiles/{id}/cdp` 代理照常可用。
- **数据目录**：`DATA_DIR` 解析顺序——env `DATA_DIR` 优先；未设置时 Windows 默认 `%APPDATA%\CloakBrowser-Manager`，其他系统维持 `/data`。
- **API 变化**：
  - `LaunchResponse.vnc_ws_port` / `display` 改为可空；
  - `/api/status` 新增 `display_mode: "native" | "vnc"`；
  - 新增 `GET /api/binary/status` → `{ready: bool, error: string | null}`，以及重试下载端点 `POST /api/binary/download`。
- **内核下载**：应用启动时若二进制缺失，在后台线程执行 `ensure_binary()`；下载状态通过 `/api/binary/status` 暴露。

## 5. 前端改动

- App 启动时从 `/api/status` 读取 `display_mode` 存入 state。
- `view === "view"` 时分流：`vnc` → 现有 `ProfileViewer`（noVNC）；`native` → 新组件 `RunningPanel`。
- **`RunningPanel`**（新）：运行状态徽标、"浏览器窗口已在桌面打开"提示、CDP 地址 + 复制按钮、Stop 按钮；轮询 profile status（约 3 秒），发现 `stopped`（用户直接关了浏览器窗口）自动切回编辑视图。
- `ProfileForm`：原生模式下隐藏 `clipboard_sync` 选项；其余字段保留（`headless` 在原生模式 = 后台无窗口运行；`screen_width/height` 决定窗口初始尺寸与指纹）。
- 内核未就绪时显示"正在下载浏览器内核…"横幅并禁用 Launch，失败时横幅显示错误 + 重试按钮。
- VNC 相关代码路径全部保留，零删除。
- 关窗确认模态：React 实现（「退出并关闭所有浏览器」/「最小化到托盘」/「取消」+「记住我的选择」勾选框，取消不记忆任何选择），由桌面壳通过 `evaluate_js` 触发，结果经 pywebview `js_api` 桥回传；纯浏览器访问时该模态永不出现。

## 6. 桌面壳（新增顶层 `desktop/` 目录）

`desktop/app.py` 启动流程：

1. **单实例保护**：探测固定回环端口（默认 `127.0.0.1:8977`，env 可改）能否绑定；不能 → 原生消息框提示"已在运行"后退出。
2. 设置 `USE_VNC=0`（用户显式设置的 env 优先）；数据目录由后端按 §4.2 规则解析，桌面壳不干预。
3. 同进程启动 uvicorn 线程，serve 现有 `backend.main:app`。
4. 轮询 `/api/status` 就绪后，pywebview 创建窗口加载 `http://127.0.0.1:8977`。
5. **关窗拦截**：pywebview `closing` 事件——已记住选择（`exit`/`tray`）→ 直接执行记住的动作；未记住（`ask`）且有浏览器在跑 → 触发前端模态；未记住且无浏览器在跑 → 直接退出。
6. **托盘**（pystray）：菜单「打开管理器」「重置关闭行为」「退出」；"最小化到托盘" → `window.hide()`。
7. **真正退出**：调用 `cleanup_all()` 优雅关闭所有浏览器上下文，再停服务器；超时（约 10 秒）后强制结束进程。
8. 记住的选择持久化到 `DATA_DIR/settings.json`：`{"on_close": "ask" | "exit" | "tray"}`。

## 7. 打包（PyInstaller）

- `onedir` 模式（启动快、杀软误报率低），产物 `CloakBrowserManager/CloakBrowserManager.exe`。
- 打包内容：backend 包、`frontend/dist` 静态文件（构建产物）、desktop 壳、图标。
- 资源路径（`FRONTEND_DIR` 等）改为冻结环境兼容的解析函数（处理 PyInstaller 下 `__file__` 失效问题）。
- **浏览器内核不打包**——CloakBrowser 二进制许可证禁止再分发；首次启动由 `ensure_binary()` 从官方渠道下载（约 200MB），符合许可证"用户自行从官方渠道下载"条款。
- 开发工作流：`python desktop/app.py` 源码直跑，PyInstaller 仅用于出包。

## 8. 错误处理

| 场景 | 处理 |
|------|------|
| 内核下载失败 | `/api/binary/status` 返回 `{ready: false, error}`；前端横幅 + 重试按钮 |
| 原生模式 launch 失败 | 现有 500 + 前端错误横幅机制不变 |
| 端口 8977 被占 | 单实例语义：原生消息框提示后退出 |
| 用户直接关闭浏览器窗口 | `context.on("close")` 自动清理；`RunningPanel` 轮询发现后切回编辑视图 |
| 崩溃残留 Chromium 锁文件 | 复用现有 launch 前清理逻辑 |
| 退出时 `cleanup_all()` 卡住 | 桌面壳超时强制结束进程 |

## 9. 测试

- **后端 pytest**（沿用 `backend/tests` 现有风格）：
  - `use_vnc()` 判定：env 显式值、未设置时 mock `shutil.which` 的自动探测；
  - 原生模式 launch：mock `launch_persistent_context_async`，断言不调 VNC、env 无 `DISPLAY`、args 无 swiftshader、含 `--window-size`；
  - `DATA_DIR` 解析（env 优先 / Windows 默认值）；
  - models：`vnc_ws_port` / `display` 可空；
  - clipboard 端点原生模式返 501；
  - `/api/binary/status` 端点。
- **前端 vitest**：按 `display_mode` 分流渲染；`RunningPanel` 渲染、Stop、CDP 复制、轮询切视图。
- **手动验收（Windows）**：源码模式全流程；PyInstaller 包首启下载内核 → 建 profile → Launch 桌面弹窗 → 指纹检测页通过 → 关窗对话框（两种选择 + 记住）→ 托盘还原/退出 → 退出后无残留进程。
- **Docker 回归**：`docker compose up` 确认 VNC 模式行为不变。

## 10. 范围外

- macOS / Linux 客户端打包
- 自动更新、代码签名
- 下载进度百分比（cloakbrowser 若无进度 callback 则只显示"下载中"）
- Docker/VNC 模式的任何行为变更

## 11. 实现时需验证的外部 API 细节

以下依赖 `cloakbrowser` 包内部实现，设计已给出预期行为，实现第一步先验证：

1. `launch_persistent_context_async` 是否支持 `no_viewport=True`（或等价方式取消 viewport 强制）；若不支持，原生模式退化为 viewport = 屏幕尺寸。
2. `ensure_binary()` 的下载目录、是否提供进度 callback、失败时的异常类型。
3. Windows 下 `--window-size` 与 CloakBrowser 指纹参数的兼容性。
