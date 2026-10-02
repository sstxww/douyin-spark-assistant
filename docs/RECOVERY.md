# 独立自动补漏（Windows + GitHub 双触发）

GitHub 原生 cron 仍保留 08:17、20:17（UTC+8）。另在自己的 Windows 电脑注册 `Spark-Assistant-Recovery`，每 5 分钟检查，周期对齐 :02/:07/:12/:17…，Windows 登录时也检查一次。程序内部始终按 UTC+8 计算，不受电脑显示为其他时区影响。

这不是只发提醒：当本轮有未开始的对象、没有任务在运行、云端发送开关已开启且当前代码/配置检查有效时，补漏助手直接调用 GitHub 的 workflow_dispatch 启动原发送程序。无需保持 ChatGPT、本机配置台或浏览器打开。

## 部署与状态

完成本机登录、发布、全部账号检查和开启发送后，在仓库目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-watchdog.ps1
```

安装脚本使用当前 Windows 用户的 Interactive 登录方式、Limited 权限，不收集 Windows 密码、不复制 GitHub Token、不安装自托管 Actions Runner、不开放网络端口、不修改休眠或电源设置。任务默认通过 pythonw.exe 运行，不弹黑框，但可在 Windows 任务计划程序中看到。

**电脑必须开机、联网、Windows 用户保持登录。锁屏不等于注销；注销、关机或休眠期间，本机补漏不会运行。** 这时仅有原 GitHub cron 兜底，其延迟问题并未消失。恢复登录/唤醒后，在当前轮允许的时间内检查缺失结果；不会跨日追发。

本机配置台新增“独立自动补漏”卡片，显示最后检查时间及已确认/未开始/待核对数量。超过 12 分钟无更新会显示警示。状态文件位于 `.local/web-local/watchdog-status.json`；Windows 任务计划程序的 `LastTaskResult` 为 0 表示本次本机检查正常，不代表接收方已读。

## 安全与恢复策略

- 补漏助手不读取抖音 Cookie。发布时只导出仓库、配置版本、时间、安装指纹和 HMAC 对象标识到 `watchdog-plan.json`；真实登录与文案继续保存在原位置。
- 仅按已发布配置启动。草稿不会被自动发布；云端暂停、配置版本不同或当前代码缺少有效检查时停止。重新在本机发布会同步计划投影。
- 判断依据是每个对象在云端 ledger 的 `ui_confirmed`，不是工作流绿色勾。全部已确认就不再创建发送任务。
- 同一对象同一轮的 `reserved` 表示结果未知，绝不清除记录或强制重发。改代码、重启、重复点击不会增加该轮名额。
- 本机每轮最多主动触发 6 次。临时失败后按 5、10、20、30、60 分钟退避；请求超时也先计入次数，避免响应丢失造成触发风暴。API 不通时下次五分钟检查再尝试，不自动重置预算。
- 已知登录失效、风控、对象/标题/草稿错误不连续重试，保留错误状态。临近下一轮或午夜前 10 分钟不再创建补漏任务。
- 所有实际发送仍经过原 GitHub 工作流和同一个持久化去重记录。若两种触发同时到达，工作流串行执行、后来的任务按记录跳过。
- 云端现在逐个对象处理，彼此使用独立浏览器上下文；普通单对象错误不阻止其他对象。账号级 AUTH/RISK 仍停止该账号后续操作。
- 已预留但未确认的条目会让发送运行以未完成退出，不再误报全成功。成功只表示已有抖音页面确认，不是送达回执、已读证明或火花保证。

## 暂停与卸载

日常暂停仍使用本机配置台“暂停后续自动发送”，或将仓库变量 `SPARK_WEB_ENABLED` 改为 `false`；双触发都会遵守它。已在运行的任务要另外取消。

仅移除本机补漏任务（不删除登录、配置或云端计划）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-watchdog.ps1 -Remove
```

诊断时可运行只读评估，不启动任何任务：

```powershell
python -m spark.watchdog --dry-run
```

状态码 `dispatched` 表示已请求执行、尚不表示消息已发送；`confirmed` 表示此轮计划内的对象已有页面确认。`needs_attention`、`retry_exhausted`、`check_required`、`plan_stale`、`window_ending`、`error` 都不能当作本轮发送成功。

## 真实边界

这个版本解决“只依赖一个延迟的 cron 且漏跑无人自动处理”这一点；没有消除 GitHub 执行服务、网络、电脑供电和抖音登录权限这些依赖，也没有接收方送达回执。不能承诺 100% 送达或永久免维护。无新增付费服务；沿用已有 GitHub Actions，资源使用仍受账户自身额度和政策约束。

技术依据：
- GitHub 定时事件和延迟说明：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- 官方主动触发接口：https://docs.github.com/rest/actions/workflows#create-a-workflow-dispatch-event
- Windows 任务登录模式：https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype

故障模拟覆盖：cron 未触发、已在排队、部分成功、结果不确定、API 响应丢失、退避及上限、手动暂停、旧版本配置、跨时段及跨日期、安全验证、逐对象执行。模拟测试不会访问抖音或发送真实消息。
