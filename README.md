# 🔥 火花小助手 · GitHub 网页版

**在浏览器里扫码、选账号、选好友、保存文案；GitHub Actions 每天执行。**

[![测试](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/test.yml/badge.svg)](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/test.yml)

## 先点这里

### [→ 首次创建 GitHub 私有配置环境](https://codespaces.new/sstxww/douyin-spark-assistant?quickstart=1)

[以后打开原来的 Codespace](https://github.com/codespaces) · [网页版运行记录](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/spark-web.yml) · [完整图文式操作说明](docs/WEB.md)

> 这是 **GitHub Codespaces 私有网页 + GitHub Actions 定时任务**，不是 GitHub Pages，也不是在公开 Actions 日志里展示登录二维码。无需在本机安装 Python、Git 或插件。Codespaces 首次创建需要你确认，计算和存储有额度，超额可能收费；请检查自己的预算。
>
> **实验性网页自动化，不是抖音官方接口。** 代码/模拟页面测试不等于你的账号已通过真实扫码和发送验收。抖音云端网络、页面调整、登录过期和安全验证可能阻止运行；不会破解验证码或绕过验证，也不保证火花一定延续。默认不发送消息。

## 四步使用

**1. 打开配置台。** 点击上面的创建链接，确认创建 Codespace，等待环境自动安装。浏览器会打开“火花小助手”；没有弹出时，在工作区下方 **Ports（端口）→ 8765 → 在浏览器中打开**。端口始终保持 **Private（私有）**，不要改成 Public。

**2. 连接 GitHub、添加抖音账号。** 在配置台按“连接 GitHub”完成官方设备验证码授权；然后到“账号与扫码登录”添加账号，点击“扫码登录”。在私有预览中点抖音的“登录 / 扫码登录”，用本人手机抖音扫一扫。看到私信页面并核对账号后，勾选确认，点“保存登录并导入会话”。二维码/预览不会放入公开日志或仓库。

**3. 选择好友、保存文案。** 在“对象与文案”选择账号，加入已加载会话，或者手动填写唯一备注。设置共用或专属文案，点“保存对象与文案”。文案可保存为模板，之后一键套用。建议第一次只配置一个账号、一位好友。

**4. 发布 → 检查 → 开启。** 在“发布与自动发送”设置时间，依次点 **“发布私密配置到 GitHub” → “全部账号只检查” → 检查成功后“开启每日自动发送”**。发布会先暂停发送，当前代码与配置版本的全账号检查不通过时，面板不会允许开启。

之后可以停止 Codespace，电脑也不必常开。每天的发送由 Actions 完成；扫码失效时重新打开原 Codespace 处理。GitHub 定时任务可能延迟或停用，仍需关注运行记录。

## 已实现

| 功能 | 网页版行为 |
| --- | --- |
| 多个账号 | 最多 3 个本人账号（a1 / a2 / a3），独立登录状态、独立好友与文案，按账号启用/停用。不是批量运营工具。 |
| 选择对象 | 导入当前已加载的私信会话；可手动添加精确备注。启用账号合计最多 10 位好友。不会读取完整通讯录。 |
| 自定义文案 | 共用文案、每人专属文案；固定、按日期轮换、每日随机；支持 `{name}`、`{date}`、`{weekday}`。 |
| 文案复用 | 文案保存成模板，套用到任一账号；每条计划可以每天重复使用。 |
| 立即执行 | 私有面板选择全部或单个账号，点“按已保存文案发送一次”；也可在 Actions 手动运行。 |
| 每日自动发送 | 默认 UTC+8 的 20:17，可以在网页改时间并重新发布，无须编辑 YAML。 |
| 防误发 | 精确名称和聊天标题核对；出现重名、草稿或未确认的发送状态就停止。 |
| 防重复 | 按账号、对象、日期持久化尝试记录。手动/定时共用记录；同一天不会通过重复点击强制重发。 |
| 私密与备份 | 凭据放在私有 Codespace 和 Actions Secrets；可用独立密码导出加密备份，恢复账号、文案和去重标识。 |

## 在 GitHub Actions 直接运行

打开 [网页版 · 每日火花助手](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/spark-web.yml)，点 **Run workflow**：

- `mode`：`check` 只检查；`send` 按已发布配置真实发送（必须已开启发送）。
- `account`：`all` 全部已启用账号，或私有面板对应的 `a1` / `a2` / `a3`。
- `revision`：保留 `current`；不要在这个公开输入框填写昵称、文案、密码或 Cookie。

**首次配置必须先完成私有面板扫码和发布。** 直接在空仓库点运行不会自动登录。面板的“开启”需要由面板提交、带精确版本的“全部账号检查”通过；原生 Actions 的 `current` 检查可以诊断，但不替代这个开启条件。

绿色成功可能包含“今天已经尝试，跳过”，不代表本次每个对象都新收到一条消息。页面确认也不等于火花结果，请在抖音核对。

## 暂停、恢复与复用

在私有面板点“暂停后续自动发送”。已有任务需要“紧急停止并取消任务”。无法进入面板时，在仓库 **Settings → Secrets and variables → Actions → Variables** 把 **`SPARK_WEB_ENABLED`** 改为 `false`，再到 Actions 取消正在运行的任务。

**以后请打开同一个 Codespace，不要每次重新创建。** 停止再启动会保留草稿和登录；删除则不会。删除前在面板“加密备份与恢复”导出备份，密码另存。Actions Secrets 无法通过网页或 API 读回明文；没有原工作区或备份时，不要随意删除去重标识来“重新部署”。

复用配置时不需要重新扫码，前提是原登录仍有效。同一账号重新扫码应使用原来的卡片，不要重复添加。程序依据可用登录标识尝试检测重复，但不能代替你核对真实账号，也不能保证备注变化后仍识别为同一对象。

## 数据放在哪里

| 位置 | 保存内容 |
| --- | --- |
| 私有 Codespace 的 `.local/web/` | 登录状态、草稿、模板、去重密钥及 GitHub CLI 授权。GitHub CLI 在没有系统凭据库时可能以文件保存授权；该目录不能公开、不能提交。 |
| Actions Secrets | `SPARK_WEB_MANIFEST`，以及 `SPARK_WEB_A1` / `A2` / `A3`。gzip/base64 只是编码，平台 Secrets 提供保护。单账号超过容量会拒绝发布。 |
| Actions Variables | `SPARK_WEB_ENABLED`、配置版本和高熵密钥的安装指纹；不存昵称、文案或登录状态。 |
| `spark-state` 分支 | 日期和 HMAC 对象标识、`reserved` / `ui_confirmed`，不含昵称或文案。公开仓库仍可看到运行数量、时间等元数据。 |
| 你导出的备份 | 密码派生密钥 + AES-GCM 加密的私有数据，不包含 GitHub CLI 授权。密码丢失无法恢复。 |

GitHub CLI 官方授权可能覆盖你的其他仓库，并非单仓库最小权限；请阅读面板说明与官方授权页。拥有仓库写权限的人可以通过修改工作流访问 Secrets，因此不要给不信任的人写权限。

## 验证与旧版

```bash
python -m pip install -r requirements-web.txt
python -m playwright install --with-deps chromium
python -m unittest discover -s tests -v
```

测试使用虚构数据和模拟聊天页面，不访问真实抖音、不发送消息。详情见 [验证与边界](docs/VALIDATION.md)。

本机旧向导仍保留：[旧版使用说明](docs/LEGACY.md)。两版有独立的 Secrets/开关；**不要在同一天混用两版给同一账号/好友发送**，两版账号身份映射并非自动迁移。网页版发布会关闭旧版开关；旧版开启也会关闭网页版开关，但不会撤回已经发出的消息。

[安全说明](docs/SECURITY.md) · [兼容性](docs/COMPATIBILITY.md) · MIT License
