"""Browser acceptance of the actual isolated normal page, only after a real adoption."""
import argparse,http.server,json,re,socketserver,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();R=a.root.resolve();O=a.output.resolve();O.mkdir(parents=True,exist_ok=True)
accepted=R/'local_archive/ai_tasks/nightly/replay/recommendation/accepted-recommendation.json'
page_path=R/'local_archive/forward_monitor/style-preview/prism-a2.html'
if not accepted.exists() or not page_path.exists():
 (O/'browser.json').write_text(json.dumps({'status':'not_run','reason':'Actual adopted recommendation or normal rendered page is missing; no substitute page was created'},ensure_ascii=False,indent=2));raise SystemExit(2)
value=json.loads(accepted.read_text());html=page_path.read_text();snapshot=json.loads(re.search(r'<script id="snapshot" type="application/json">(.*?)</script>',html,re.S).group(1));stock=next(s for s in snapshot['stocks'] if s['code']=='300658.SZ' and s['recDate']=='2026-09-22')
(O/'normal-page-stock.json').write_text(json.dumps(stock,ensure_ascii=False,indent=2)+'\n');(O/'adopted-section.md').write_text(value['section']);(O/'normal-statement.md').write_text(stock['statementFull'])
# The renderer removes stock heading; retain all body and existing source/heading formatting.
def compact(s):return re.sub(r'\s+','',s)
body=re.sub(r'^### [^\n]+\n','',value['section'],count=1).strip()
body_equal=compact(body)==compact(stock['statementFull'])
class Quiet(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*args,**kw):super().__init__(*args,directory=str(R/'local_archive/forward_monitor'),**kw)
 def log_message(self,*args):pass
with socketserver.TCPServer(('127.0.0.1',0),Quiet) as server:
 threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_address[1]}/style-preview/prism-a2.html'
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto(url,wait_until='networkidle');page.locator('button[data-stock="300658.SZ:2026-09-22"]').click();dialog=page.get_by_role('dialog');dialog.get_by_role('button',name='研究说明',exact=True).click()
  (O/'normal-dom.txt').write_text(dialog.inner_text());dialog.screenshot(path=str(O/'normal-top.png'))
  scrollable=dialog.locator('*').evaluate_all('(els)=>els.filter(e=>e.scrollHeight>e.clientHeight+10).map(e=>{e.scrollTop=e.scrollHeight;return e.className})')
  dialog.screenshot(path=str(O/'normal-bottom.png'))
  meaning=json.loads((O/'frozen-research-check.json').read_text()) if (O/'frozen-research-check.json').exists() else {'status':'not_run'}
  report=dict(status='passed' if body_equal and not errors and meaning.get('status')=='passed' else 'failed',frozen_research_check=meaning.get('status'),body_equal=body_equal,errors=errors,title=page.title(),normal_selector='button[data-stock="300658.SZ:2026-09-22"] → 研究说明',scrollable_elements=scrollable,browser='Playwright Chromium',source='Actual isolated renderer page; no hand-built screenshot or new diagnostic panel')
  (O/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');browser.close()
 server.shutdown()
print(json.dumps(report,ensure_ascii=False))
