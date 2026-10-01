# 🔥 火花小助手

**给指定好友，每天一句自定义问候。GitHub 定时执行，本机向导配置。**

[![Tests](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/test.yml/badge.svg)](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/test.yml)
[运行记录](https://github.com/sstxww/douyin-spark-assistant/actions/workflows/spark.yml) · [安全说明](docs/SECURITY.md) · [兼容性与限制](docs/COMPATIBILITY.md)

> **这是实验性网页自动化，不是抖音官方续火花接口。** 代码测试不代表你的账号已实测通过；网页调整、登录失效、云端网络和验证要求都可能使任务停止。程序只能代你尝试发送消息，不能保证火花一定延续，也不会代替对方互动。默认关闭真实发送。

## 能做什么

| 需求 | 操作 |
| --- | --- |
| 选对象 | 扫码后导入当前已加载会话，多选加入；也能手动添加唯一备注。列表勾选或取消，最多 10 位。 |
| 自定义文案 | 共用文案或每位好友专属文案；固定、轮换、每日随机三种模式。 |
| 每天自动执行 | 默认 UTC+8 的 **20:17**；向导输入时间即可修改，不用自己算 cron。 |
| 无须每天开电脑 | 完成初次配置和检查后，由 GitHub 托管运行；登录过期时仍需本机重新扫码。 |
| 先试再发 | “只检查不发送”只验证查找好友和聊天标题，不输入文字、不发送。 |
| 防误发、防重复 | 精确名称与聊天标题双重核对；发送前持久化当天尝试记录，结果不确定时不自动重试。 |
| 隐私 | 登录、好友和文案保存在本机及 GitHub Secrets；不提交登录文件、不上传聊天截图。 |

## 首次使用：三个页面

### 0. 打开向导

电脑需有 **Python 3.11+** 与 **GitHub CLI**。Windows Python 安装时勾选 `Add Python to PATH`。

首次使用 GitHub CLI，在终端运行：

```powershell
gh auth login -h github.com -w -s repo,workflow
```

只在 GitHub 官方授权页完成登录；不要把 Token 发给别人。已经登录的电脑通常无需重复登录；若修改定时失败，检查是否有 `workflow` 权限。

在仓库点击 **Code → Download ZIP**，解压，Windows 双击 **`start.bat`**。它会在项目目录创建 `.venv`、安装锁定版本的 Playwright 和浏览器，然后打开中文向导。首次安装需要联网。

macOS / Linux 可以运行 `bash start.sh`；还需系统提供 Tk 图形库及 Chromium 所需运行库。当前主要面向 Windows 配置体验。

### 1. 登录账号

点 **打开抖音扫码登录**，在新打开的浏览器里用本人账号扫码。确认能看到私信会话后，回到向导点击 **我已登录，保存并导入会话**。

在加载出的会话中选中好友，再点 **把选中会话加入发送对象**。只导入当前已加载的会话，不会抓取完整通讯录；导入为空时可以手动输入好友的唯一备注。

### 2. 对象与文案

建议第一次只配置 **1 位好友**。勾选目标，填写共用文案；需要专属文案时，在列表选中好友，编辑下方文字，点击 **保存该对象的专属文案**。

每行是一条候选消息，例如：

```text
今天也来和你打个招呼～{date} 🔥
{name}，{weekday}快乐，记得好好吃饭。
```

固定模式使用第一条；轮换模式按日期轮换；随机模式每天选一条、当天重复检查保持相同选择。

**昵称相同、好友改名、特殊字符或找不到对象时，先在抖音为好友设置唯一备注。** 本程序不会模糊匹配，也不会“随便点第一个结果”。更改备注后需重新上传配置。

### 3. 部署与开关

确认仓库是你的 `用户名/douyin-spark-assistant`，设置 UTC+8 时间，然后：

1. 点 **上传私密配置到 GitHub**。这一步会先暂停发送，再更新 Secrets 和定时配置。
2. 点 **只检查不发送**，再点 **打开 GitHub 运行结果**。等待该任务显示成功，展开日志确认所有对象通过。
3. 核对好友、文案及对方意愿，勾选确认框，点 **开启每日发送**。

想马上试发一次，可以在 GitHub → Actions → 每日火花助手 → Run workflow 中选择 `send`；必须先开启发送开关。当天已有尝试记录的对象会跳过。

后续改对象、文案或时间，重新上传即可。**每次上传会暂停发送，检查后需再次开启。** 仅保存本机、不上传的修改不会影响 GitHub。

## GitHub 中实际保存了什么

| 位置 | 名称 | 内容 |
| --- | --- | --- |
| Actions Secret | `DOUYIN_STATE` | gzip + base64 编码的 Playwright 登录状态。编码不是加密；由 Secrets 负责服务端保护。 |
| Actions Secret | `SPARK_CONFIG` | 好友、文案、配置标识和时间。 |
| Actions Secret | `SPARK_KEY` | 生成去重 HMAC 标识的随机密钥。 |
| Actions Variable | `SPARK_ENABLED` | 只有字符串 `true` 才允许真实发送。默认 `false`。 |
| `spark-state` 分支 | `ledger.json` | 日期、HMAC 对象标识、`reserved` / `ui_confirmed`，不包含昵称、文案或登录数据。 |

公开仓库的运行日志、调度时间、状态分支和大致运行数量仍是公开的。Secrets 不是对仓库维护者的隔离边界：拥有写权限的人可能修改代码读取它们，请不要给不信任的人仓库写权限。

## 常见问题

**显示 AUTH / RISK。** 登录过期或页面需要验证。先暂停任务，在本人设备处理，再重新扫码、上传、检查。程序不破解验证码、不规避风控，也不承诺长期免登录。

**显示 TARGET / HEADER / EDITOR。** 找不到唯一对象、无法确认标题、输入框不符合预期或有草稿。此时程序停止；请在本机抖音核对唯一备注、草稿及网页是否变化。不要通过取消身份核对来“修复”。

**显示 UNCERTAIN / REJECTED。** 本次可能已经触发发送。请在抖音手动核对；当天不会自动重试。即使只是网络中断，也优先避免重复发送。

**显示 LEDGER。** 去重记录读取或持久化失败，不会继续发送。检查 Actions 的 `contents: write` 权限、`spark-state` 分支和 GitHub 网络。不要为重发随意删分支或重建密钥；这会破坏历史去重依据。首次初始化中断且分支没有 `ledger.json` 时，应由维护者确认没有发生发送后修复空记录。

**为什么不是准点执行？** [GitHub 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)说明定时任务可能延迟，负载高时也可能丢弃排队任务。不建议把续火花安排在午夜前几分钟。

**很久没用后任务不跑？** [GitHub 说明](https://docs.github.com/en/actions/managing-workflow-runs/disabling-and-enabling-a-workflow)公开仓库在 60 天无活动时可能自动禁用定时任务。重新上传配置会尝试启用工作流；也可在 Actions 手动启用。不要把本项目当作永久免维护服务。

**怎么停止？** 在向导点击 **暂停每日发送**，或把仓库变量 `SPARK_ENABLED` 改为 `false`。已经启动的任务需要另在 Actions 点击 **Cancel workflow**；暂停不会撤回已发送的消息。

**能不能完全只用手机？** 这个版本的首次扫码配置需要电脑。完成后可在手机 GitHub 页面查看运行记录和暂停工作流。它不是手机 App，也不是托管网页登录后台。

## 开发与验证

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
```

包含配置校验、UTC+8 调度、HMAC 去重、写入失败停止、模拟聊天页的精确匹配与发送状态测试。模拟测试不会访问抖音或发送真实消息；真实账号验收必须由账号持有人完成。

实现入口：`setup_gui.py`（本机配置）、`run.py`（云端任务）、`spark/browser.py`（网页兼容层）、`spark/ledger.py`（持久化去重）。

仅使用本人授权账号及双方同意的低频互动，请自行确认适用的平台规则。原生表情、图片、群发营销、多账号批量运营、验证码绕过不在本版本范围内。

## License

本仓库原创代码采用 MIT License。兼容性参考和依赖说明见 [COMPATIBILITY.md](docs/COMPATIBILITY.md)。
