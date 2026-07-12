# Native Desktop Client — 遗留事项（2026-07-11 分支完成时记录）

> 来源：`feature/native-desktop-client` 全分支终审（22+5 commits, 9e2ee07..42b383e）。
> 终审结论：**Ready to merge**（无 Critical；两个 Important 已在 fix wave 修复并加测试锁定）。
> 本文件代替 bd issue（本机无 bd CLI）；合并后可转录进 issue 跟踪。

## 必做：人工验收（计划内设计为人工，需 GUI / 真实内核 / Docker）

1. **Task 18 Step 2 — 源码模式桌面验收（8 项清单）**
   前置 `cd frontend && pnpm build`；运行 `backend/.venv/Scripts/python.exe -m desktop.app`。
   清单见 `docs/superpowers/plans/2026-07-11-native-desktop-client.md` Task 18 Step 2（窗口、内核横幅、原生弹窗、检测页渲染、关窗回编辑、Stop、CloseModal 三选、记住偏好+托盘还原）。
2. **Task 20 Step 5 — 打包产物验收**
   `dist/CloakBrowserManager/CloakBrowserManager.exe` 已构建（uvicorn 动态导入已打包并在盘上确认）；需真机双击运行复跑 Task 18 清单 + 首启下载 + 单实例 + 数据目录（现默认为 **exe 同级目录**：`profiles/`、`profiles.db`、`settings.json`；2026-07-12 起不再用 `%APPDATA%`）。**重点观察后端线程启动路径**（uvicorn 冻结导入是终审指出的风险点，已预防性修复）。另验收：Settings 中修改内核存储位置（Browse 选目录 → Save → 重新下载/识别内核）。
3. **Task 20 Step 6 — Docker/VNC 回归**
   `docker compose up --build` → `/api/status` 的 `display_mode == "vnc"`；Launch 出 noVNC 画面；剪贴板同步可用；**无持续的内核下载横幅**（镜像预下载内核，ready 应瞬时为 true）。

## 建议：合并后改进（终审 DEFER 清单，均不阻塞）

- 数据目录 2026-07-12 改为 exe 同级后，旧 `%APPDATA%\CloakBrowser-Manager` 数据**不自动迁移**（发布前无真实用户，按设计放弃；如需找回旧测试数据，设 `DATA_DIR` 指回即可）。
- Settings 修改内核存储位置后，旧位置的内核目录**不清理**（约 200MB 残留，用户可手删；`~/.cloakbrowser` 默认位置同理）。

- VNC 路径 `launch()` 无端到端回归测试（历史空缺，本分支靠 diff 审查保障）。
- `desktop/settings.py`：原子写（temp + os.replace）；`UnicodeDecodeError` 加入兜底 except。
- `Controller.running_count()`：pywebview GUI 线程上同步 urlopen(timeout=2)，后端不可达时关窗最多冻结 2s；可改异步/缩短。
- vitest 共享 `setupFiles` 引 jest-dom（当前每个组件测试文件单独 import）。
- `use_vnc()` 每次调用做 PATH 扫描；可在启动时缓存（注意保持"进程内模式不变"语义）。
- main.py VNC 专用端点（websockify 代理、Xvnc 日志尾读）对 display/ws_port 的非空假设：原生 UI 不可达，纯防御性加固。
- `desktop/build.md` 写 `pnpm install`，而仓库锁定文件是 npm 的 `package-lock.json`（Docker 用 npm）；统一说法。
- `_message_box` 错误场景可用 MB_ICONERROR（现统一 INFO 图标）。
- BinaryManager 失败后重试成功不会补跑 auto-launch（该进程内手动 Launch 即可；微行为，按设计接受）。

## 环境备注

- `frontend/pnpm-lock.yaml`、`pnpm-workspace.yaml`、`frontend/tsconfig.tsbuildinfo` 已 gitignore（本地运行 pnpm 的产物；仓库包管理器记录为 npm）。
- 构建产物 `build/`、`dist/` 已 gitignore，留在盘上供 Step 5 验收直接使用。
