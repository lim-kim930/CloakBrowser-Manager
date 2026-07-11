# Task 1 — cloakbrowser 预检结论

在 Windows 上针对已安装的 `cloakbrowser 0.4.10` 实测（backend `.venv`，Python 3.14.3）。

## 结论摘要

- **no_viewport: 支持**
  `cloakbrowser.launch_persistent_context_async` 的签名以 `**kwargs: Any` 结尾（透传 Playwright），
  因此 `no_viewport=True` 会被接受。→ Task 5 使用计划默认写法 `launch_kwargs["no_viewport"] = True`，无需回退。

  完整签名：
  ```
  (user_data_dir, headless=True, proxy=None, args=None, stealth_args=True,
   user_agent=None, viewport=<default>, locale=None, timezone=None,
   color_scheme=None, geoip=False, humanize=False, human_preset='default',
   human_config=None, extension_paths=None, license_key=None,
   browser_version=None, **kwargs) -> Any
  ```

- **ensure_binary 返回: `str`（二进制绝对路径）**
  `cloakbrowser.download.ensure_binary(license_key=None, browser_version=None) -> str`。
  下载目录为用户主目录下的 `~/.cloakbrowser/`（本机实测 `get_binary_path()` →
  `C:/Users/LIMKIM/.cloakbrowser/chromium-146.0.7680.177.5/chrome.exe`）。
  注意：**不是** `%APPDATA%\CloakBrowser-Manager`（那是本项目的 DATA_DIR，存 profiles/DB/settings）。

- **就绪查询 API: 存在**（`get_binary_path()`、`binary_info()`；另有私有 `_pro_binary_ready`）
  - `get_binary_path(version=None, pro=False) -> Path`
  - `binary_info(browser_version=None) -> dict`
  - `check_platform_available() -> None`

## 对 Task 5 / Task 7 的影响

- **Task 5**：预检结论与计划默认一致（支持 no_viewport）。**按计划默认代码实现，不走回退。**

- **Task 7**：预检结论与计划的默认假设（"无就绪查询 API"）**相反** —— 实际存在
  `get_binary_path()`。计划 Task 7 的「预检回退」注释将此优化标为可选（"可…"）。
  **控制器决定：Task 7 仍按计划默认实现**（依赖 `ensure_binary()` 幂等性），理由：
  1. 计划提供的三条 pytest 用例是基于"无预检、start() 后立即 downloading=True、ensure_binary 调用一次"的契约编写的；采用同步就绪检查会要求改写这些既定测试，偏离计划。
  2. `ensure_binary()` 在暖启动时幂等快速返回，是计划记录的兜底，可用。
  3. 该优化被计划显式标为可选。
  暖启动延迟若成为体验问题，作为后续 issue 处理（非本次范围）。
