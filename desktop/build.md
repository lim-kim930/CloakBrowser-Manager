# 构建 Windows 客户端

## 前置
- Windows 10/11 x64，已装 Edge WebView2 Runtime（Win11 自带）。
- Python 3.12+（构建环境实测 3.14）（用 `backend/.venv`）。

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
- 换图标：替换 `_placeholder_icon()`，或在 spec 的 `EXE(..., icon=os.path.join(ROOT, "desktop/assets/icon.ico"))` 指定（spec 里相对路径按 spec 所在的 `desktop/` 目录解析，所以要用 `ROOT` 锚定到仓库根）。
