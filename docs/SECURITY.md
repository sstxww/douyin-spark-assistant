# 安全与隐私

登录状态具有账号访问能力，应像密码一样保护。不要在聊天、Issue、截图或日志中粘贴 Cookie、`DOUYIN_STATE`、GitHub Token、`.local` 中的任何文件。

## 默认边界

- 默认不开启真实发送；手动运行默认是 `check`。`check` 不输入、不发送，但会打开相应聊天界面。
- 本机图形向导不启动 HTTP 服务，不使用远程配置网站或统计 SDK，不读取现有 Chrome 的配置文件。扫码使用新的 Playwright 浏览器上下文。
- 文件只保存在项目的 `.local/`，该目录已被 Git 忽略。Unix 尽量使用目录 0700、文件 0600；Windows 仍依赖账户自身的 NTFS 权限。不要将整个项目目录共享给其他人。
- 配置只通过已登录的 GitHub CLI 传入自己的仓库，Secret 值走标准输入，不放在命令行参数中。
- 发送工作流不对 PR 开放、不上传截图和浏览器跟踪、不打印原始异常。依赖安装步骤不接收抖音 Secrets。
- 同时运行使用同一并发组；每天的对象尝试先以 HMAC 标识写入 `spark-state` 分支，再触发发送。失败或无法确认就保留 `reserved`，不自动重发。
- “去重”是尽力实现的每对象每日最多一次发送尝试，不是分布式端到端 exactly-once 交付。删除状态、改变密钥/账号标识/好友备注、修改代码、绕过工作流会破坏此约束。

## 仍然公开的信息

仓库代码、定时配置、Actions 状态、运行时刻、对象序号、匿名状态记录都是公开的。不承诺对使用行为完全匿名。需要更强的行为隐私时，应使用私有仓库并自行确认 Actions 用量规则。

## 维护与失效

使用者应定期查看运行结果和抖音实际消息状态。GitHub 定时执行没有准点保证；抖音账号或网页变更可能让程序失效。遇到验证码或验证要求时，程序停止，不尝试绕过。

暂停只阻止新任务，不撤回已经发送的消息，也不保证中止已经启动的任务。紧急情况请取消正在运行的 Actions，关闭开关，删除相关 Secrets，并在抖音端退出相关登录设备。

不要通过公开 Issue 报告含个人数据的安全问题。只提交去除凭据、昵称、文案和截图后的复现步骤。

## 参考

- [GitHub：在 Actions 中使用 Secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
- [Playwright：登录状态可能包含可用于冒用账号的敏感数据](https://playwright.dev/python/docs/auth)
- [GitHub CLI：Secret 值在发送到 GitHub 前于本地加密](https://cli.github.com/manual/gh_secret_set)
