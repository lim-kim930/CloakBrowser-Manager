# 内核手动管理 + 版本管理 + Profile 级内核选择（2026-07-12）

> 分支：`feature/native-desktop-client`。实现于 Task 1–10（每 Task 一 commit）。
> 本文件代替 bd issue（本机无 bd CLI）。

## 背景与目标

Native 桌面客户端此前启动即 `binary_mgr.start()` 自动后台下载内核（~200MB）。改为：

1. **Native 去自动下载** — 用户自行从官方渠道下载内核，应用内手动导入/选目录。
2. **内核版本管理** — 列出/导入/删除已装内核，可设默认版本（多版本并存）。
3. **Profile 级内核选择** — 建/改 profile 时选内核版本，启动按所选版本运行。

**VNC/Docker 冻结面不变**：镜像预下载内核、启动即 ready，保留 `binary_mgr.start()`、`POST /api/binary/download`、location 变更后 `start()` 全部原样；所有改动 native-gated（`use_vnc()`）。

## 关键机制

`cloakbrowser` 包（v0.4.10）的 `launch_persistent_context_async(browser_version=...)` 支持版本 pin；当 `<kernel_dir>/chromium-<version>/chrome.exe` 已存在时 `ensure_binary` 直接返回、**零网络**。多版本天然共存于缓存目录。故：

- 内核管理 = 在 `effective_kernel_dir()` 上扫描/导入/删除 `chromium-<version>/` 目录。
- Profile 选择 = profiles 表存版本串、启动时传 pin。
- 包内 `executable_path` 硬编码，**无法**按 profile 指定任意路径 exe → 必须走托管目录布局。

`backend/kernel_manager.py` 刻意不 import `cloakbrowser`：目录命名是稳定契约（镜像自 `config.py` 的 `get_binary_dir`/`get_binary_path`），且后端测试整包 mock 掉了 cloakbrowser。

## 重要设计决定：版本号不自动探测（P1）

chrome.exe 的 PE FileVersion 只有 4 段（`146.0.7680.177`），而官方目录/release tag 是 5 段（`146.0.7680.177.5`，末段是 CloakBrowser 构建迭代号，不在二进制里）。若按 FileVersion 命名目录，unpinned 启动会 miss → 反而触发下载；4 段 pin 的下载 URL 也会 404。因此**导入时版本必填**（来自用户/release tag），或从 `chromium-<version>` 源目录名自动取。校验 regex `^[0-9]+(?:\.[0-9]+){3,4}$`。UI 提示用户参照 GitHub release tag `chromium-v<version>`。

## 实现摘要

- **backend/kernel_manager.py**（新）：`list_kernels`/`kernel_installed`/`any_kernel_installed`、`resolve_kernel_version`（显式→默认→最新→None）、`import_kernel`（zip 安全解压 staging+原子 rename / 目录改名或复制）、`delete_kernel`（防路径穿越、清默认）、`get/set_default_version`。
- **backend/binary_manager.py**：加 `mark_ready(bool)`（同步就绪，无下载）。
- **backend/main.py**：lifespan native 分支 `mark_ready(any_kernel_installed())` + `CLOAKBROWSER_AUTO_UPDATE=false`；`GET /api/binary/status` native 实时扫描；`POST /api/binary/download` native→501；`PUT /api/binary/location` native 重扫不下载；`GET /api/status` native 报解析版本或 "not installed"；新增 `GET /api/kernels`、`POST /api/kernels/import`、`DELETE /api/kernels/{version}`（占用 409）、`PUT /api/kernels/default`（`_kernel_lock` 序列化）。
- **backend/browser_manager.py**：`launch()` 分配前 `_resolve_launch_kernel`；native 永远 pin 已验证版本（无内核 raise），VNC 仅显式 pin 且预检；`RunningProfile.kernel_version` 记录。
- **backend/models.py / database.py**：`kernel_version` 字段（validator）；`ALTER TABLE profiles ADD COLUMN kernel_version TEXT` 迁移 + INSERT/update 白名单；kernel API 模型。
- **desktop/api_bridge.py**：`pick_file(file_types)`（OPEN_DIALOG）+ `pywebview.d.ts` 类型。
- **frontend**：`api.ts` kernel 客户端+类型；`ProfileForm` 内核下拉（Default/已装/未装 disabled 项）；`SettingsModal` Browser kernels 区（列表+默认单选+删除+导入 zip/目录/文本兜底+releases 链接）；`App.tsx` native 无内核横幅（VNC 分支原样）。

## 人工验收

见 `native-desktop-followups.md` Task 20 Step 5（内核手动管理清单）与 Step 6（VNC 回归）。要点：空目录启动无下载横幅+Launch 禁用；导入 zip/目录后可用；pinned 启动日志无下载；删除占用内核 409；换存储位置重扫无下载；VNC 侧 `ready` 瞬时 true、行为不变。

## 自动化测试

- 后端：`test_kernel_manager.py`（扫描/解析/导入 zip+目录/删除/穿越拒绝）、`test_kernels_api.py`（端点+占用 409+默认）、`test_binary_location.py`（native 重扫不下载、native/VNC lifespan）、`test_api.py`（status/download 模式分支、profile kernel_version 往返）、`test_browser_manager_native.py`（native 必 pin/无内核 raise、VNC 无 pin 不变/缺失 raise/装了透传）、`test_database.py`。
- 前端：`api.test.ts`、`ProfileForm.test.tsx`、`SettingsModal.test.tsx`（含 P3：mock 补齐 kernel 函数）。
- 桌面：`test_api_bridge.py`（pick_file）。
- 命令：`backend/.venv/Scripts/python.exe -m pytest -q`（285+ 通过）、`cd frontend && npm test && npm run build`。
