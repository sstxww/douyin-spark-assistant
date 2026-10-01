# 本机登录，GitHub 复用登录态

Windows 双击 `start-local.bat`。程序在项目内安装独立依赖，打开 `http://127.0.0.1:8767`，不会启动 Codespace，也不用抓包插件。

## 第一次

1. 面板复用这台电脑已经授权的 GitHub CLI。未授权时使用面板的“连接 GitHub”，只在 GitHub 官方页面完成授权；不要发送 Token。
2. 默认创建没有好友的“我的账号”卡片。点击“在本机登录”，在弹出的独立抖音浏览器使用网页提供的扫码、验证码或密码方式登录。
3. 看到私信并核对当前账号后，回到面板，勾选确认，再“保存登录并导入会话”。只有完成这一保存，关闭窗口后才能复用。
4. 选择真正需要联系的好友和文案，发布到 Actions Secrets、全部账号检查、开启每日发送。默认文案只是草稿，不会自动群发。

## 以后

再次打开同一个目录中的启动程序，点击原账号卡片的“打开抖音 / 复用登录态”，会加载已保存的 Cookie、localStorage 与 IndexedDB 等状态。不从日常 Chrome 用户目录提取密码或其他网站 Cookie。

正常使用中网页可能更新会话。回到面板重新保存后，再重新发布、检查，才能更新云端副本。没有实现、也不承诺绕过平台的自动续期或永久 Token。注销、会话过期、额外验证等情况下，需要本人重新登录。

本机登录成功不等于云端接受这份状态。请先检查 GitHub Actions；失败时保持暂停，不去绕过抖音验证。完成发布后本机可以关机，云端使用的是最近发布的副本。

账号、对象、模板和去重密钥存于本机 `.local/web-local/workspace.json`，不公开、不提供 Cookie 下载接口，但本机文件本身不加密，应按密码保护。更换目录前使用“加密备份与恢复”；不要把该 JSON 发到聊天或提交到 GitHub。已有 Codespace 配置应先加密备份并在本机恢复，以保留账号和去重标识。Actions Secrets 不能读回明文，不应重建密钥来强制重发。

本机服务只监听 `127.0.0.1:8767`，具有 Host/Origin/CSRF 检查。不要做公网或局域网端口转发。拥有本机操作系统账户访问权的人仍可访问本机文件；拥有仓库写权限的人仍可能修改工作流读取 Secrets。

技术依据：[Playwright 登录态保存与复用](https://playwright.dev/python/docs/auth)、[GitHub Actions Secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)。这只是可过期的会话复用，不是官方“永久续火花”接口。
