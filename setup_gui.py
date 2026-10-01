"""Local-only desktop setup. No web server, no external analytics, no credentials in argv."""
from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import tkinter as tk
import uuid
import webbrowser
from tkinter import messagebox, ttk
from spark.core import Config, LOCAL, SafeError, pack_state, save_private
from spark import deploy


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.login_done = threading.Event()
        self.login_active = False
        self.targets = []
        self.account_id = uuid.uuid4().hex
        self.repo = tk.StringVar(value="sstxww/douyin-spark-assistant")
        self.clock = tk.StringVar(value="20:17")
        self.mode = tk.StringVar(value="轮换")
        self.status = tk.StringVar(value="尚未启用发送。先扫码登录，再配置好友。")
        self.ack = tk.BooleanVar(value=False)
        root.title("火花小助手 · 本机安全配置")
        root.geometry("1000x780")
        root.minsize(870, 700)
        root.configure(bg="#f5f5f7")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f5f7")
        style.configure("TLabel", background="#f5f5f7", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("TButton", padding=(12, 8), font=("Microsoft YaHei UI", 10))
        style.configure("TNotebook.Tab", padding=(18, 10))
        header = ttk.Frame(root, padding=(24, 18))
        header.pack(fill="x")
        ttk.Label(header, text="每天一句，留住小火花", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="公开代码 · 私密配置 · 默认不发送 · 只用于双方同意的好友互动").pack(anchor="w", pady=(6, 0))
        book = ttk.Notebook(root)
        book.pack(fill="both", expand=True, padx=24)
        self.login_tab = ttk.Frame(book, padding=20)
        self.target_tab = ttk.Frame(book, padding=20)
        self.deploy_tab = ttk.Frame(book, padding=20)
        for title, tab in [("1  登录账号", self.login_tab), ("2  对象与文案", self.target_tab), ("3  部署与开关", self.deploy_tab)]:
            book.add(tab, text=title)
        self.build_login()
        self.build_targets()
        self.build_deploy()
        ttk.Label(root, textvariable=self.status, wraplength=930, padding=(24, 16)).pack(fill="x")
        self.load()
        root.after(100, self.poll)

    def notice(self, text):
        self.status.set(text)

    def task(self, function, success="操作完成。", callback=None):
        if self.busy:
            messagebox.showinfo("正在操作", "请先完成当前操作。")
            return
        self.busy = True
        self.notice("正在处理；请勿重复点击。")
        def work():
            try:
                result = function()
                self.events.put(("done", (success, callback, result)))
            except SafeError as exc:
                self.events.put(("error", str(exc)))
            except Exception:
                self.events.put(("error", "操作失败。请检查网络、依赖、GitHub 登录状态及网页是否正常；私人数据未输出。"))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.notice(value)
                elif kind == "done":
                    self.busy = False
                    self.login_active = False
                    text, callback, result = value
                    self.notice(text)
                    if callback:
                        callback(result)
                elif kind == "error":
                    self.busy = False
                    self.login_active = False
                    self.notice(value)
                    messagebox.showerror("已停止", value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def build_login(self):
        tab = self.login_tab
        ttk.Label(tab, text="使用一个全新的浏览器窗口扫码，不读取你现有浏览器的登录信息。", wraplength=820).pack(anchor="w")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=16)
        ttk.Button(actions, text="打开抖音扫码登录", command=self.login).pack(side="left")
        ttk.Button(actions, text="我已登录，保存并导入会话", command=self.save_login).pack(side="left", padx=12)
        ttk.Label(tab, text="操作顺序：扫码 → 在新窗口确认能看到私信会话 → 回到这里点保存。\n只导入当前页面已加载的会话，不是完整好友列表。找不到的人可在下一页手动添加唯一备注。",
                  wraplength=820).pack(anchor="w", pady=8)
        ttk.Label(tab, text="当前加载的会话（可按 Ctrl 多选）").pack(anchor="w", pady=(15, 5))
        self.contacts = tk.Listbox(tab, selectmode="extended", height=12, exportselection=False,
                                   font=("Microsoft YaHei UI", 11))
        self.contacts.pack(fill="both", expand=True)
        ttk.Button(tab, text="把选中会话加入发送对象", command=self.add_contacts).pack(anchor="w", pady=10)
        ttk.Label(tab, text="登录文件只写入本机 .local 文件夹；上传时经 GitHub CLI 存入 Secrets。\n不要把 .local 文件夹、Cookie 或登录文件发给别人。", wraplength=820).pack(anchor="w")

    def login(self):
        if self.busy:
            return
        self.login_done.clear()
        self.login_active = True
        def work():
            from playwright.sync_api import sync_playwright
            from spark.browser import CHAT_URL, SEARCH, health, imported_contacts, unique
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                try:
                    context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
                    page = context.new_page()
                    page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=60_000)
                    self.events.put(("status", "请在新窗口扫码登录；看到私信页面后，点击“我已登录，保存并导入会话”。"))
                    deadline = time.monotonic() + 900
                    while not self.login_done.is_set():
                        if time.monotonic() > deadline or page.is_closed():
                            raise SafeError("AUTH")
                        page.wait_for_timeout(250)
                    health(page)
                    unique(page.locator(SEARCH), "AUTH")
                    state = context.storage_state(indexed_db=True)
                    pack_state(state)
                    save_private(LOCAL / "state.json", json.dumps(state, ensure_ascii=False))
                    return imported_contacts(page)
                finally:
                    browser.close()
        def imported(names):
            self.contacts.delete(0, "end")
            for name in names:
                self.contacts.insert("end", name)
            if not names:
                self.notice("登录文件已保存；未识别到已加载会话，请在下一页手动添加好友唯一备注，并先检查。")
        self.task(work, "登录文件已保存到本机。请选择会话，或在下一页添加唯一备注。", imported)

    def save_login(self):
        if self.login_active:
            self.login_done.set()
        else:
            messagebox.showinfo("尚未开始", "请先点击“打开抖音扫码登录”。")

    def build_targets(self):
        tab = self.target_tab
        add = ttk.Frame(tab)
        add.pack(fill="x")
        self.name = ttk.Entry(add, width=35)
        self.name.pack(side="left", fill="x", expand=True)
        ttk.Button(add, text="添加唯一备注 / 昵称", command=self.add_manual).pack(side="left", padx=8)
        self.tree = ttk.Treeview(tab, columns=("enabled", "name", "custom"), show="headings", height=7)
        for column, title, width in [("enabled", "发送", 70), ("name", "好友唯一备注 / 精确昵称", 300), ("custom", "文案", 150)]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)
        self.tree.pack(fill="x", pady=10)
        self.tree.bind("<<TreeviewSelect>>", self.select_target)
        self.tree.bind("<Double-1>", lambda _: self.toggle())
        controls = ttk.Frame(tab)
        controls.pack(fill="x")
        ttk.Button(controls, text="勾选 / 取消", command=self.toggle).pack(side="left")
        ttk.Button(controls, text="移除", command=self.remove).pack(side="left", padx=8)
        ttk.Label(controls, text="最多 10 位；同名请先在抖音设置唯一备注。").pack(side="left")
        ttk.Label(tab, text="所有对象共用文案（每行一条，可用 {name}、{date}、{weekday}）").pack(anchor="w", pady=(16, 5))
        self.messages = tk.Text(tab, height=4, font=("Microsoft YaHei UI", 10))
        self.messages.insert("1.0", "今天也来和你打个招呼～{date} 🔥")
        self.messages.pack(fill="x")
        ttk.Label(tab, text="当前选中对象的专属文案（每行一条；留空后保存 = 使用共用文案）").pack(anchor="w", pady=(12, 5))
        self.custom = tk.Text(tab, height=3, font=("Microsoft YaHei UI", 10))
        self.custom.pack(fill="x")
        ttk.Button(tab, text="保存该对象的专属文案", command=self.save_custom).pack(anchor="w", pady=8)

    def add_name(self, name):
        name = name.strip()
        if not name or len(name) > 80:
            return
        if any(t["name"] == name for t in self.targets):
            return
        if len(self.targets) >= 10:
            messagebox.showinfo("已达上限", "个人互动工具最多配置 10 位对象。")
            return
        self.targets.append({"name": name, "enabled": True, "messages": None})
        self.refresh()

    def add_manual(self):
        self.add_name(self.name.get())
        self.name.delete(0, "end")

    def add_contacts(self):
        for i in self.contacts.curselection():
            self.add_name(self.contacts.get(i))
        self.notice("已加入对象列表，请到“对象与文案”页面检查。")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.targets):
            self.tree.insert("", "end", iid=str(i), values=("✓" if t["enabled"] else "—", t["name"], "专属" if t.get("messages") else "共用"))

    def selected(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else None

    def select_target(self, event=None):
        i = self.selected()
        self.custom.delete("1.0", "end")
        if i is not None:
            self.custom.insert("1.0", "\n".join(self.targets[i].get("messages") or []))

    def toggle(self):
        i = self.selected()
        if i is not None:
            self.targets[i]["enabled"] = not self.targets[i]["enabled"]
            self.refresh()

    def remove(self):
        i = self.selected()
        if i is not None:
            self.targets.pop(i)
            self.refresh()

    def save_custom(self):
        i = self.selected()
        if i is None:
            messagebox.showinfo("请选择对象", "先在上方列表单击一位好友。")
            return
        self.targets[i]["messages"] = [s.strip() for s in self.custom.get("1.0", "end").splitlines() if s.strip()] or None
        self.refresh()
        self.notice("该对象的文案已更新；最后需上传配置才会在 GitHub 生效。")

    def build_deploy(self):
        tab = self.deploy_tab
        ttk.Label(tab, text="GitHub 仓库（只操作当前 gh 登录账号自己拥有的仓库）").pack(anchor="w")
        ttk.Entry(tab, textvariable=self.repo, width=65).pack(anchor="w", fill="x", pady=6)
        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=12)
        ttk.Label(controls, text="每天 UTC+8 时间：").pack(side="left")
        ttk.Entry(controls, textvariable=self.clock, width=8).pack(side="left")
        ttk.Label(controls, text="  文案模式：").pack(side="left")
        ttk.Combobox(controls, textvariable=self.mode, values=("固定", "轮换", "每日随机"), state="readonly", width=12).pack(side="left")
        ttk.Label(tab, text="上传会自动暂停发送。之后先“只检查不发送”，看过结果再开启。\n首次使用请仅选择 1 位好友。GitHub 定时任务可能延迟，不建议设置在午夜前。", wraplength=820).pack(anchor="w", pady=8)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=15)
        ttk.Button(row, text="保存本机配置", command=self.save_config).pack(side="left")
        ttk.Button(row, text="上传私密配置到 GitHub", command=self.upload).pack(side="left", padx=8)
        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=8)
        ttk.Button(row2, text="只检查不发送", command=self.check).pack(side="left")
        ttk.Button(row2, text="打开 GitHub 运行结果", command=self.results).pack(side="left", padx=8)
        ttk.Checkbutton(tab, variable=self.ack, text="我确认对象和文案正确，对方同意每日互动，并已查看检查结果。").pack(anchor="w", pady=(24, 12))
        row3 = ttk.Frame(tab)
        row3.pack(fill="x")
        ttk.Button(row3, text="开启每日发送", command=self.enable).pack(side="left")
        ttk.Button(row3, text="暂停每日发送", command=self.disable).pack(side="left", padx=8)
        ttk.Label(tab, text="注意：暂停只阻止尚未开始的新任务。要停止已运行的任务，请在 GitHub Actions 点 Cancel workflow。\n登录失效需要重新扫码。程序只自动发送你这一侧的消息，不承诺火花一定延续。\n不保存聊天截图，不打印好友姓名和文案；GitHub 的公开状态记录只含日期和匿名键。",
                  wraplength=820).pack(anchor="w", pady=24)
        ttk.Label(tab, text="尚未登录 GitHub CLI？在终端执行：gh auth login -h github.com -w -s repo,workflow", wraplength=820).pack(anchor="w")

    def raw(self):
        data = {"version": 1, "account_id": self.account_id, "time": self.clock.get().strip(),
                "mode": {"固定": "fixed", "轮换": "cycle", "每日随机": "random"}[self.mode.get()],
                "messages": [s.strip() for s in self.messages.get("1.0", "end").splitlines() if s.strip()],
                "targets": self.targets}
        Config.parse(data)
        return data

    def save_config(self):
        try:
            raw = self.raw()
            save_private(LOCAL / "config.json", json.dumps(raw, ensure_ascii=False, indent=2))
            save_private(LOCAL / "repository.txt", self.repo.get().strip())
            self.notice("配置只保存在本机 .local。上传后才会在 GitHub 生效。")
            return raw
        except (SafeError, OSError) as exc:
            messagebox.showerror("配置未保存", str(exc) if isinstance(exc, SafeError) else "无法保存本地配置。")
            return None

    def load(self):
        try:
            if (LOCAL / "repository.txt").exists():
                self.repo.set((LOCAL / "repository.txt").read_text(encoding="utf-8").strip())
            raw = json.loads((LOCAL / "config.json").read_text(encoding="utf-8"))
            Config.parse(raw)
            self.account_id = raw["account_id"]
            self.targets = raw["targets"]
            self.clock.set(raw["time"])
            self.mode.set({"fixed": "固定", "cycle": "轮换", "random": "每日随机"}[raw["mode"]])
            self.messages.delete("1.0", "end")
            self.messages.insert("1.0", "\n".join(raw["messages"]))
            self.refresh()
        except (OSError, ValueError, SafeError, KeyError):
            pass

    def upload(self):
        raw = self.save_config()
        if raw is None:
            return
        repo = self.repo.get().strip()
        # Immutable snapshot; edits made during upload cannot alter the submitted config.
        raw = json.loads(json.dumps(raw))
        def work():
            if not (LOCAL / "state.json").exists():
                raise SafeError("AUTH")
            state = json.loads((LOCAL / "state.json").read_text(encoding="utf-8"))
            key_path = LOCAL / "key.txt"
            if not key_path.exists():
                save_private(key_path, secrets.token_hex(32))
            deploy.upload(repo, raw, state, key_path.read_text(encoding="utf-8").strip())
        self.task(work, "配置已上传，真实发送保持暂停。请先运行“只检查不发送”。")

    def check(self):
        repo = self.repo.get().strip()
        self.task(lambda: deploy.check_run(repo), "已提交检查任务；请点“打开 GitHub 运行结果”查看是否通过。检查不发消息。")

    def results(self):
        import re
        repo = self.repo.get().strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            webbrowser.open(f"https://github.com/{repo}/actions/workflows/spark.yml")

    def enable(self):
        if not self.ack.get():
            messagebox.showinfo("尚未确认", "请先完成只检查不发送，查看结果，并勾选确认框。")
            return
        repo = self.repo.get().strip()
        if messagebox.askyesno("确认开启", "将按最后一次上传的对象、文案和时间每天发送。\n本机未上传的修改不会生效。确定开启吗？"):
            self.task(lambda: deploy.set_enabled(repo, True), "GitHub 每日发送已开启，按最后上传的配置运行。")

    def disable(self):
        repo = self.repo.get().strip()
        self.task(lambda: deploy.set_enabled(repo, False), "新发送任务已暂停；已运行任务请在 Actions 页面取消。")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
