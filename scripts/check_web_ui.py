import sys,tempfile,json,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from fastapi.testclient import TestClient
from webui.server import create_app
from playwright.sync_api import sync_playwright
from unittest.mock import patch
with tempfile.TemporaryDirectory() as d:
 app=create_app(Path(d), 'owner/demo',hosts={'testserver'})
 client=TestClient(app)
 def request(source,path,options):
  headers=options.get('headers',{});headers['Origin']='http://testserver'
  r=client.request(options.get('method','GET'),path,headers=headers,content=options.get('body'))
  return {'status':r.status_code,'body':r.text,'headers':dict(r.headers)}
 with patch.object(app.state.cloud,'status',return_value={'connected':False,'enabled':False,'runs':[]}):
  with sync_playwright() as p:
   b=p.chromium.launch(headless=True,executable_path=os.getenv("SPARK_TEST_BROWSER"))
   page=b.new_page(viewport={'width':1440,'height':1100});errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.expose_binding('__fixtureRequest',request)
   def render():
    html=(root/'webui/static/index.html').read_text().replace('<link rel="stylesheet" href="/static/style.css">','<style>'+(root/'webui/static/style.css').read_text()+'</style>').replace('<script src="/static/app.js" defer></script>','')
    page.set_content(html)
    page.evaluate("() => {window.fetch = async (path, options={}) => {const r=await window.__fixtureRequest(path,options);return new Response(r.body,{status:r.status,headers:r.headers});};}")
    # Scope to a function, permitting a clean UI reload in the same blank document.
    page.add_script_tag(content='(()=>{'+(root/'webui/static/app.js').read_text()+'})();')
    page.wait_for_function("document.getElementById('repository').textContent.includes('/')")
   def screenshot(name):
    destination=os.getenv('SPARK_UI_SCREENSHOT_DIR')
    if destination:
     Path(destination).mkdir(parents=True,exist_ok=True)
     page.evaluate('window.scrollTo(0,0)')
     page.screenshot(path=str(Path(destination)/name),full_page=True)
   render()
   screenshot('spark-web-start.png')
   page.locator('nav [data-tab="accounts"]').click()
   page.locator('#accountLabel').fill('演示主号')
   page.locator('#addAccount').click()
   page.locator('[data-edit="a1"]').wait_for()
   page.locator('[data-edit="a1"]').click()
   page.locator('#targetName').fill('演示好友 A');page.locator('#addTarget').click()
   page.locator('#messages').fill('今天也来和你打个招呼 🔥\n{name}，{weekday}快乐！')
   page.locator('#targetRows textarea').fill('给你的专属问候，{date} 🌻')
   page.locator('#saveSettings').click()
   page.wait_for_function("document.querySelector('#notice').textContent.includes('草稿已保存')")
   page.locator('#templateTitle').fill('日常问候模板');page.locator('#saveTemplate').click()
   page.wait_for_function("document.querySelector('#notice').textContent.includes('文案模板已保存')")
   screenshot('spark-web-messages.png')
   page.locator('nav [data-tab="accounts"]').click()
   page.locator('#accountLabel').fill('演示备用号');page.locator('#addAccount').click()
   page.locator('[data-edit="a2"]').wait_for();page.locator('[data-edit="a2"]').click()
   page.locator('#templateSelect').select_option(label='日常问候模板');page.locator('#applyTemplate').click()
   assert '{weekday}' in page.locator('#messages').input_value()
   page.locator('#targetName').fill('演示好友 B');page.locator('#addTarget').click();page.locator('#saveSettings').click()
   page.wait_for_function("document.querySelector('#notice').textContent.includes('草稿已保存')")
   page.locator('#selectedAccount').select_option('a1')
   assert '专属问候' in page.locator('#targetRows textarea').input_value()
   page.locator('#selectedAccount').select_option('a2')
   assert '{weekday}' in page.locator('#messages').input_value()
   page.locator('nav [data-tab="deploy"]').click();page.locator('#checkAll').click()
   page.wait_for_function("document.querySelector('#notice').textContent.includes('尚未发布')")
   screenshot('spark-web-deploy.png')
   page.set_viewport_size({'width':390,'height':844})
   page.locator('nav [data-tab="messages"]').click()
   screenshot('spark-web-mobile.png')
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile overflow'
   assert not errors, errors
   print(json.dumps({'UI':'PASS','transport':'in-memory HTTP fixture; no external websites','flows':['two accounts','recipient and override save','template save and reuse','switch account','unpublished run blocked','mobile layout'],'javascript_errors':errors},ensure_ascii=False))
   b.close()
 client.close()
