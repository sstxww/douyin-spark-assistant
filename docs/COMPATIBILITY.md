# 兼容性和验收边界

## 当前实现

普通 Playwright Chromium，通过抖音网页的可见搜索、聊天标题、输入框、发送按钮和消息状态工作。不调用非公开私信 API，不伪造设备签名，不使用反检测浏览器或验证码绕过。

本仓库的 GUI、配置结构、调度、隐私处理、去重和网页操作实现为独立编写。网页 DOM 类名的兼容性研究参考了公开项目：

- 项目：[unmev/douyin-auto-fire](https://github.com/unmev/douyin-auto-fire)
- 研究时固定提交：`af0035f764d3a1adac5884bc3d73adcf031a3dd6`
- 对照文件：`app/selectors.py`、`app/douyin.py`、`app/sender.py`

本仓库未打包上述项目的实现源码，也不在运行时从其主分支下载代码。该项目有自己的许可证；本仓库的 MIT 许可不改变任何第三方项目的许可。

依赖 Playwright 的官方资料：

- [Python 登录状态](https://playwright.dev/python/docs/auth)
- [定位元素](https://playwright.dev/python/docs/locators)
- [安装与运行浏览器](https://playwright.dev/python/docs/browsers)

## 验收需要分层

1. 配置和去重测试：验证输入、时间转换、HMAC 标识和失败停止。
2. 本地模拟 DOM 测试：验证精确匹配、重名停止、标题核对、草稿保护、发送等待与延迟失败。并非真实抖音页面测试。
3. GitHub CI：验证相同代码能在 GitHub 托管 Linux 环境安装并通过模拟测试。
4. 本人账号 `check`：确认登录和对象查找在实际云端环境可用，不发送。
5. 本人账号低频真实发送：在抖音端核对消息与火花。代码作者不能从步骤 1–3 推断步骤 4–5 一定成功。

## 明确限制

导入的是当前已加载的会话，非全量好友列表。只有文案和文字 Emoji，不提供原生表情接口。精确昵称仍可能发生重名，因此优先使用唯一备注；网页变化时宁可失败，也不放宽身份核对。

网页出现新消息且在观察窗口内无失败或等待标记，只记为 `ui_confirmed`。这不是服务器交付回执，更不是火花续期成功回执。超时、网络中断、任务取消等情况可能留下 `reserved`，须本人手动核对，不自动重试。

抖音官方公开的部分主动私信能力面向服务账号及授权用户，不能将它等同于普通账号的续火花接口：[官方相关文档](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/instant-message/private-message/authorize_send_msg)。
