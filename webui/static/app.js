'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let localMode = false;
let csrf = '', ws = null, repository = '', selected = '', editorSlot = '', savedPayload = '';
let activeLogin = '', loginReady = false, frameTimer = null, authTimer = null, frameURL = null, frameFetching = false;

function notice(text, kind = '') {
  $('notice').textContent = text;
  $('notice').className = `notice ${kind}`;
}
async function api(path, data, binary = false) {
  const options = {credentials:'same-origin', headers:{'X-Spark-CSRF':csrf}};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(data);
  }
  const response = await fetch(`/api/${path}`, options);
  if (binary && response.ok) return response.blob();
  let value;
  try { value = await response.json(); }
  catch (_) { throw new Error('页面访问已失效或网络异常，请重新登录 GitHub 并刷新私有页面。'); }
  if (!response.ok || value.ok === false) throw new Error(value.error || '操作失败，请检查网络和当前配置。');
  return value;
}
async function work(button, fn, progress) {
  if (button?.disabled) return;
  if (button) button.disabled = true;
  if (progress) notice(progress);
  try { await fn(); }
  catch (error) { notice(error.message || '操作失败，请刷新后重试。', 'error'); }
  finally { if (button) button.disabled = false; }
}
const account = () => ws?.accounts.find(a => a.slot === selected);
function editable() {
  return {time:ws.time, accounts:ws.accounts.map(a => ({slot:a.slot, label:a.label, enabled:a.enabled,
    config:{mode:a.config.mode, messages:a.config.messages, targets:a.config.targets}}))};
}
function collect() {
  if (!ws) return;
  const a = account();
  if (a && editorSlot === selected) {
    a.enabled = $('accountEnabled').checked;
    a.config.messages = $('messages').value.split('\n').map(s=>s.trim()).filter(Boolean);
    a.config.mode = $('messageMode').value;
    for (const row of $('targetRows').querySelectorAll('[data-target]')) {
      const i = Number(row.dataset.target);
      if (a.config.targets[i]) {
        a.config.targets[i].enabled = row.querySelector('input').checked;
        const lines = row.querySelector('textarea').value.split('\n').map(s=>s.trim()).filter(Boolean);
        a.config.targets[i].messages = lines.length ? lines : null;
      }
    }
  }
  ws.time = $('sendTime').value;
}
function setView(data) {
  ws = data.workspace;
  localMode = data.runtime?.local === true;
  repository = data.repository;
  if (!ws.accounts.some(a=>a.slot === selected)) selected = ws.accounts[0]?.slot || '';
  savedPayload = JSON.stringify(editable());
  render();
}
function render() {
  $('localInfo').hidden = !localMode;
  $('cloudOnlyIntro').hidden = localMode;
  if (localMode) {
    $('workspaceLocation').textContent = '本机私有配置 · 仅 127.0.0.1';
    $('authScopeDescription').textContent = '本机模式复用这台电脑上 GitHub CLI 已有的授权，不复制或上传 GitHub Token。能否使用以顶部连接状态为准。尚未连接时才需要下面的官方授权；GitHub CLI 权限并非仅限本仓库。';
    $('loginHelp').textContent = '请在弹出的本机抖音浏览器正常登录，支持网页提供的扫码、验证码或密码方式。已有登录态会优先复用。看到私信并核对账号后，回到此面板勾选并保存。不要把密码或 Cookie 发到聊天里。';
    $('loginExpiryHelp').textContent = '登录窗口最多保留 15 分钟。登录态可能过期或被撤销，不存在永久有效保证。保存后，修改云端配置需要重新发布并检查。';
    $('backupHelp').textContent = '本机关闭后重新打开，保存的登录态和配置仍在。换电脑或删除程序前导出加密备份；不要直接发送 workspace.json。Actions Secrets 不能直接读回明文。';
    $('runtimeHelp').textContent = '实验性网页自动化，不是抖音官方接口。本机登录成功不保证 GitHub 云端接受相同登录态；必须先云端检查。遇到额外验证会停止，不绕过验证，也不保证火花结果。配置完成后可以关闭本机面板。';
  }
  document.querySelector('#loginDialog .screen-wrap').hidden = localMode;
  $('refreshFrame').hidden = localMode;
  $('repository').textContent = repository;
  $('repoLink').href = `https://github.com/${repository}`;
  $('actionsLink').href = `https://github.com/${repository}/actions/workflows/spark-web.yml`;
  $('publishState').textContent = ws.published ? '配置：已发布' : '配置：草稿 / 尚未发布';
  $('sendTime').value = ws.time;
  renderSchedule();
  $('accountCards').innerHTML = ws.accounts.length ? ws.accounts.map(a => `
    <article class="card account-card"><h3><span class="slot">${escapeHTML(a.slot)}</span>${escapeHTML(a.label)}</h3>
      <span class="pill">${a.logged_in ? '已保存登录 · 需云端检查' : '尚未登录'}</span>
      <p>${a.enabled ? '参与计划' : '未参与计划'} · ${a.config.targets.filter(t=>t.enabled).length} 位已选好友<br><span class="small">${a.saved_at ? '保存于 '+escapeHTML(a.saved_at) : '扫码后登录信息仅保存在私有工作区和 Secrets。'}</span></p>
      <div class="button-row"><button class="primary" data-login="${a.slot}">${localMode ? (a.logged_in ? '打开抖音 / 复用登录态' : '在本机登录') : (a.logged_in ? '重新扫码' : '扫码登录')}</button><button data-edit="${a.slot}">设置好友</button></div>
      <button class="text-button" data-remove-account="${a.slot}">从草稿移除</button>
    </article>`).join('') : '<div class="empty">添加一个本人抖音账号，从扫码开始。</div>';
  $('selectedAccount').innerHTML = ws.accounts.map(a=>`<option value="${a.slot}">${a.slot} · ${escapeHTML(a.label)}</option>`).join('');
  $('selectedAccount').value = selected;
  const runSelection = $('runAccount').value;
  $('runAccount').innerHTML = '<option value="all">全部已启用账号</option>' + ws.accounts.filter(a=>a.enabled).map(a=>`<option value="${a.slot}">${a.slot} · ${escapeHTML(a.label)}</option>`).join('');
  if ([...$('runAccount').options].some(o=>o.value===runSelection)) $('runAccount').value=runSelection;
  renderEditor();
}
function renderSchedule() {
  const value = $('sendTime').value;
  if (!/^\d{2}:\d{2}$/.test(value)) return;
  const [hour, minute] = value.split(':').map(Number);
  const first = hour % 12;
  const fmt = h => String(h).padStart(2,'0')+':'+String(minute).padStart(2,'0');
  $('scheduleSummary').textContent = `每天 ${fmt(first)}、${fmt(first+12)}（UTC+8）各一次；同一时段不重复发送。修改后需要重新发布和检查。`;
}
$('sendTime').addEventListener('input', renderSchedule);
function renderEditor() {
  const a = account();
  editorSlot = a?.slot || '';
  $('noAccount').hidden = !!a;
  $('messageEditor').hidden = !a;
  $('accountEnabled').disabled = !a;
  if (!a) return;
  $('selectedAccount').value = selected;
  $('accountEnabled').checked = a.enabled;
  $('messages').value = a.config.messages.join('\n');
  $('messageMode').value = a.config.mode;
  $('importedContacts').innerHTML = a.contacts.map(n=>`<option value="${escapeHTML(n)}">${escapeHTML(n)}</option>`).join('');
  $('targetRows').innerHTML = a.config.targets.length ? a.config.targets.map((t,i)=>`
    <div class="target-row" data-target="${i}"><input type="checkbox" aria-label="启用 ${escapeHTML(t.name)}" ${t.enabled?'checked':''}>
      <span class="target-name">${escapeHTML(t.name)}</span><textarea rows="2" aria-label="${escapeHTML(t.name)} 的专属文案" placeholder="专属文案，每行一条；留空使用共用文案">${escapeHTML((t.messages||[]).join('\n'))}</textarea><button data-remove-target="${i}" class="danger-text">移除</button></div>`).join('') : '<p class="muted small">还没有发送对象。添加后先检查，不会自动发送。</p>';
  $('templateSelect').innerHTML = '<option value="">选择一个已保存模板…</option>'+ws.templates.map(t=>`<option value="${t.id}">${escapeHTML(t.title)}</option>`).join('');
}
function go(tab) {
  if (!['github','accounts','messages','deploy'].includes(tab)) return;
  collect();
  for (const panel of document.querySelectorAll('.panel')) panel.hidden = panel.id !== `panel-${tab}`;
  for (const nav of document.querySelectorAll('nav [data-tab]')) nav.classList.toggle('active',nav.dataset.tab===tab);
  if (tab==='messages') renderEditor();
}
async function syncDraft() {
  collect();
  const payload = editable();
  if (JSON.stringify(payload) !== savedPayload) setView(await api('settings', payload));
}
function requirePublished() {
  collect();
  if (!ws.published || JSON.stringify(editable()) !== savedPayload) throw new Error('存在尚未发布的草稿。请先点击“发布私密配置到 GitHub”，再执行检查。');
}
function updateAuth(data) {
  $('githubState').textContent = data.connected ? `GitHub：${data.login} 已连接` : 'GitHub：未连接或权限不足';
  $('sendState').textContent = data.enabled === null ? '自动发送：尚未读取' : `自动发送：${data.enabled ? '已开启' : '已暂停'}`;
  const auth = data.auth || {};
  $('deviceFlow').hidden = !['starting','waiting'].includes(auth.status);
  $('deviceCode').textContent = auth.code || '正在生成…';
  if (['connected','failed'].includes(auth.status) || data.connected) {
    if (authTimer) clearInterval(authTimer);
    authTimer = null;
  }
  if (auth.status==='failed' && !data.connected) notice('GitHub 授权未完成或账号不匹配。请使用仓库所有者账号重新授权。','error');
  $('runs').innerHTML = data.runs?.length ? data.runs.map(r=>{
    const states={queued:'排队中',in_progress:'运行中',completed:'已结束',waiting:'等待中'};
    const conclusions={success:'成功（请查看摘要）',failure:'失败',cancelled:'已取消',skipped:'已跳过',timed_out:'超时'};
    const validURL=String(r.url).startsWith(`https://github.com/${repository}/actions/runs/`);
    return `<div class="run-row"><div>${validURL?`<a href="${escapeHTML(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(r.title)}</a>`:escapeHTML(r.title)}<time>${escapeHTML(new Date(r.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))} UTC+8</time></div><span class="run-status ${r.conclusion==='failure'?'failed':''}">${escapeHTML(conclusions[r.conclusion]||states[r.status]||r.status)}</span></div>`;
  }).join('') : '<p class="muted">暂无网页版运行记录。发布后点击“全部账号只检查”。</p>';
}
async function refreshCloud() { updateAuth(await api('cloud')); }
async function refreshFrame() {
  if (localMode || !activeLogin || !loginReady || frameFetching || !$('loginDialog').open) return;
  frameFetching=true;
  try {
    const blob=await api('login/frame',undefined,true);
    if (!activeLogin || !$('loginDialog').open) return;
    if (frameURL) URL.revokeObjectURL(frameURL);
    frameURL=URL.createObjectURL(blob);
    $('loginFrame').src=frameURL;
  } finally {frameFetching=false;}
}
async function openLogin(slot) {
  await syncDraft();
  activeLogin=slot; loginReady=false;
  $('loginTitle').textContent=`${slot} · ${ws.accounts.find(a=>a.slot===slot).label} / ${localMode ? '本机登录与复用' : '扫码登录'}`;
  $('loginConsent').checked=false;
  $('loginFrame').removeAttribute('src');
  $('loginDialog').showModal();
  try {
    await api('login/start',{slot});
    loginReady=true;
    if (localMode) {
      notice('本机抖音窗口已打开，优先复用已有登录态。登录完成后回到此面板确认保存。');
    } else {
      await refreshFrame();
      notice('在私有预览中完成扫码。看到私信后勾选确认，再保存登录。');
      frameTimer=setInterval(()=>refreshFrame().catch(e=>notice(e.message,'error')),3000);
    }
  } catch(e) { await closeLogin(); throw e; }
}
async function closeLogin() {
  activeLogin='';loginReady=false;
  if (frameTimer) clearInterval(frameTimer);frameTimer=null;
  if (frameURL) URL.revokeObjectURL(frameURL);frameURL=null;
  $('loginFrame').removeAttribute('src');
  if ($('loginDialog').open) $('loginDialog').close();
  await api('login/close',{});
}
function addTarget(name) {
  const a=account();
  name=name.trim();
  if (!a || !name) throw new Error('请先选择账号并填写好友的完整备注。');
  if (a.config.targets.some(t=>t.name===name)) return;
  if (a.config.targets.length>=10) throw new Error('每个账号最多保存 10 位好友，所有启用账号合计最多启用 10 位。');
  a.config.targets.push({name,enabled:true,messages:null});
}

// Delegated dynamic controls. Untrusted names/texts are always escaped above.
document.addEventListener('click',event=>{
  const button=event.target.closest('button');
  if (!button) return;
  if (button.dataset.tab) return go(button.dataset.tab);
  if (button.dataset.login) return work(button,()=>openLogin(button.dataset.login),'正在打开独立的抖音登录预览…');
  if (button.dataset.edit) {collect();selected=button.dataset.edit;go('messages');renderEditor();return;}
  if (button.dataset.removeAccount) return work(button,async()=>{
    if (!confirm('从草稿移除此账号？这不会立即删除云端旧配置；请先暂停，再重新发布。原登录信息将从此工作区删除。')) return;
    await syncDraft();
    setView(await api('account/remove',{slot:button.dataset.removeAccount,confirmed:true}));
    notice('已从草稿移除。云端仍需暂停并重新发布。');
  });
  if (button.dataset.removeTarget!==undefined) {collect();account().config.targets.splice(Number(button.dataset.removeTarget),1);renderEditor();}
});
$('selectedAccount').addEventListener('change',event=>{collect();selected=event.target.value;renderEditor();});
$('refreshCloud').addEventListener('click',event=>work(event.currentTarget,refreshCloud,'正在读取 GitHub 状态…'));
$('githubLogin').addEventListener('click',event=>work(event.currentTarget,async()=>{
  if (!$('githubConsent').checked) throw new Error('请先阅读并勾选 GitHub 授权范围说明。');
  const result=await api('github/login',{confirmed:true});
  $('deviceFlow').hidden=false;$('deviceCode').textContent=result.auth.code||'正在生成…';
  if (authTimer) clearInterval(authTimer);
  authTimer=setInterval(()=>refreshCloud().catch(e=>notice(e.message,'error')),4000);
  notice('验证码出现后，打开 GitHub 官方授权页完成授权，再回到这里。');
}));
$('copyDevice').addEventListener('click',event=>work(event.currentTarget,async()=>{
  const code=$('deviceCode').textContent;
  if (!/^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code)) throw new Error('验证码尚未生成，请稍后刷新状态。');
  await navigator.clipboard.writeText(code);notice('一次性验证码已复制。');
}));
$('addAccount').addEventListener('click',event=>work(event.currentTarget,async()=>{
  await syncDraft();
  const data=await api('account/add',{label:$('accountLabel').value});
  selected=data.workspace.accounts.at(-1).slot;setView(data);$('accountLabel').value='';
  notice('已添加账号。点击这张卡片的“扫码登录”。','success');
}));
$('addTarget').addEventListener('click',event=>work(event.currentTarget,async()=>{collect();addTarget($('targetName').value);$('targetName').value='';renderEditor();}));
$('addImported').addEventListener('click',event=>work(event.currentTarget,async()=>{
  const names=[...$('importedContacts').selectedOptions].map(o=>o.value);collect();names.forEach(addTarget);renderEditor();
}));
$('saveSettings').addEventListener('click',event=>work(event.currentTarget,async()=>{await syncDraft();notice('对象与文案草稿已保存。到“发布与自动发送”发布后才会影响云端。','success');}));
$('saveTemplate').addEventListener('click',event=>work(event.currentTarget,async()=>{
  await syncDraft();const a=account();
  setView(await api('template/save',{title:$('templateTitle').value,mode:a.config.mode,messages:a.config.messages}));
  $('templateTitle').value='';notice('文案模板已保存。之后可以直接套用到其他账号。','success');
}));
$('applyTemplate').addEventListener('click',event=>work(event.currentTarget,async()=>{
  const t=ws.templates.find(t=>t.id===$('templateSelect').value);
  if (!t) throw new Error('请先选择一个已保存的模板。');
  collect();account().config.messages=[...t.messages];account().config.mode=t.mode;renderEditor();
  notice('已套用到当前账号的草稿。专属文案仍优先使用；需要保存并重新发布。');
}));
$('removeTemplate').addEventListener('click',event=>work(event.currentTarget,async()=>{
  const id=$('templateSelect').value;if (!id) throw new Error('请先选择模板。');
  if (!confirm('删除这个模板？已经套用的文案不会被删除。')) return;
  await syncDraft();setView(await api('template/remove',{id}));
}));
$('closeLogin').addEventListener('click',event=>work(event.currentTarget,closeLogin));
$('loginDialog').addEventListener('cancel',event=>{event.preventDefault();work(null,closeLogin);});
$('refreshFrame').addEventListener('click',event=>work(event.currentTarget,refreshFrame));
$('loginFrame').addEventListener('click',event=>work(null,async()=>{
  if (!loginReady) return;
  const rect=event.target.getBoundingClientRect();
  await api('login/click',{x:Math.min(1279,(event.clientX-rect.left)*1280/rect.width),y:Math.min(799,(event.clientY-rect.top)*800/rect.height)});
  await refreshFrame();
}));
$('finishLogin').addEventListener('click',event=>work(event.currentTarget,async()=>{
  if (!loginReady || !$('loginConsent').checked) throw new Error('请先完成扫码，在预览中核对账号，再勾选确认。');
  const data=await api('login/finish',{slot:activeLogin,confirmed:true});selected=activeLogin;
  await closeLogin();setView(data);notice('登录状态已保存在私有工作区。接下来选择好友与文案。','success');go('messages');
},'正在核对登录并保存私密状态…'));
$('publish').addEventListener('click',event=>work(event.currentTarget,async()=>{
  await syncDraft();setView(await api('publish',{}));await refreshCloud();
  notice('已发布到 Actions Secrets，发送保持暂停。下一步点击“全部账号只检查”。','success');
},'正在校验、暂停发送并发布私密配置…'));
async function run(mode,selection) {
  requirePublished();
  if (mode==='send' && !confirm('确认按已发布配置发送真实私信？本时段已经尝试过的好友会跳过；手动发送与定时共用名额，不会强制重复发送。')) return;
  await api('run',{mode,account:selection,confirmed:mode==='send'});
  await refreshCloud();notice(mode==='check'?'检查任务已提交；到运行记录确认通过后，再开启每日发送。':'发送任务已提交；请在运行记录和抖音中核对结果。','success');
}
$('checkAll').addEventListener('click',event=>work(event.currentTarget,()=>run('check','all'),'正在提交检查任务…'));
$('checkSelected').addEventListener('click',event=>work(event.currentTarget,()=>run('check',$('runAccount').value)));
$('sendOnce').addEventListener('click',event=>work(event.currentTarget,()=>run('send',$('runAccount').value)));
$('enable').addEventListener('click',event=>work(event.currentTarget,async()=>{
  requirePublished();
  if (!confirm('我已核对所有账号、对象和文案，并确认好友愿意接收。开启每天两次自动发送？')) return;
  await api('enable',{confirmed:true});await refreshCloud();notice('每日两次自动发送已开启。配置页不必常开；本机可以关机，Codespace 可停止。','success');
}));
$('pause').addEventListener('click',event=>work(event.currentTarget,async()=>{await api('pause',{});await refreshCloud();notice('已暂停后续自动发送。已经运行的任务仍需取消，已发消息不会撤回。','success');}));
$('cancel').addEventListener('click',event=>work(event.currentTarget,async()=>{
  if (!confirm('暂停发送，并取消所有正在运行或排队的火花任务？已发送的消息无法撤回。')) return;
  await api('cancel',{confirmed:true});await refreshCloud();notice('已暂停并提交取消请求，请在 Actions 确认任务已取消。','success');
}));
$('backupFile').addEventListener('change',()=>{$('backupFileName').textContent=$('backupFile').files[0]?.name||'未选择文件';});
$('exportBackup').addEventListener('click',event=>work(event.currentTarget,async()=>{
  await syncDraft();
  const data=await api('backup/export',{password:$('backupPassword').value});
  const url=URL.createObjectURL(new Blob([JSON.stringify(data.backup)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='spark-private.spark-backup.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);$('backupPassword').value='';
  notice('加密备份已导出。请另行保管密码；删除 Codespace 前确认备份已保存。','success');
}));
$('importBackup').addEventListener('click',event=>work(event.currentTarget,async()=>{
  const file=$('backupFile').files[0];if (!file || file.size>4_000_000) throw new Error('请选择有效的加密备份文件。');
  if (!confirm('用备份替换当前工作区草稿和登录信息？恢复后需要重新发布和检查。')) return;
  const backup=JSON.parse(await file.text());
  setView(await api('backup/import',{backup,password:$('backupPassword').value,confirmed:true}));
  $('backupPassword').value='';notice('备份已恢复，账号和去重标识已保留。请重新发布并检查。','success');
}));
async function boot() {
  const response=await fetch('/api/bootstrap',{credentials:'same-origin'});
  csrf=(await response.json()).csrf;
  setView(await api('state'));
  if (localMode) {
    notice('这是本机模式：在本机登录并保存，之后复用登录态。登录态不是永久 Token；先选对象、发布和检查，再开启发送。');
    go('accounts');
  }
  await refreshCloud();
}
boot().catch(e=>notice(e.message||'加载失败，请刷新私有页面。','error'));
