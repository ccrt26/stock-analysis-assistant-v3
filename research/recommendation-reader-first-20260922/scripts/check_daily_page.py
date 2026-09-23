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
  regressions=[]
  first={}
  for item in sorted(snapshot['stocks'],key=lambda x:x['recDate']):first.setdefault(item['code'],item)
  for kind in ('d20','regular_detail','checkpoint_detail'):
   eligible=[(item,r) for item in first.values() for r in item.get('reviews',[]) if r.get('date') in snapshot.get('sessionDates',[]) and (bool(r.get('finalTwentyDayReview')) if kind=='d20' else r.get('review_kind')==kind)]
   if not eligible:
    regressions.append({'kind':kind,'status':'not_run','reason':'No matching real archived review accessible within the isolated page sessions'});continue
   item,r=sorted(eligible,key=lambda x:(x[1]['date'],x[0]['code']))[-1];key=item['code']+':'+item['recDate']
   if dialog.is_visible():
    page.get_by_role('button',name='关闭详情',exact=True).click();dialog.wait_for(state='hidden')
   page.locator('[data-nav="records"]').click()
   row=page.locator('tr[data-stock="'+key+'"]')
   if not row.count():
    regressions.append({'kind':kind,'status':'not_run','reason':'Actual row unavailable in normal records view','key':key});continue
   row.click();dialog.get_by_role('button',name='完整复盘',exact=True).click();dialog.get_by_label('个股查看日期',exact=True).select_option(r['date'])
   text=dialog.inner_text();(O/(kind+'-dom.txt')).write_text(text);dialog.screenshot(path=str(O/(kind+'-page.png')))
   (O/(kind+'-source.json')).write_text(json.dumps({'key':key,'review':r},ensure_ascii=False,indent=2)+'\n')
   if kind=='d20':expected=r['finalTwentyDayReview']['final_twenty_day_review']['overall_review'];present=bool(dialog.locator('.final-review').count())
   else:
    paragraphs=[v for v in str(r.get('copy') or r.get('summary_copy') or '').split('\n\n') if v]
    if paragraphs and paragraphs[0]==r.get('headline'):paragraphs.pop(0)
    expected='\n\n'.join(paragraphs);present=bool(dialog.locator('.full-review').count())
   regressions.append({'kind':kind,'key':key,'date':r['date'],'status':'passed' if present and expected and compact(expected) in compact(text) else 'failed','full_source_text_present':bool(expected and compact(expected) in compact(text))})
  (O/'existing-review-display.json').write_text(json.dumps(regressions,ensure_ascii=False,indent=2)+'\n')
  meaning=json.loads((O/'frozen-research-check.json').read_text()) if (O/'frozen-research-check.json').exists() else {'status':'not_run'}
  report=dict(status='passed' if body_equal and not errors and meaning.get('status')=='passed' and all(r['status']=='passed' for r in regressions) else 'failed',existing_review_display=regressions,frozen_research_check=meaning.get('status'),body_equal=body_equal,errors=errors,title=page.title(),normal_selector='button[data-stock="300658.SZ:2026-09-22"] → 研究说明',scrollable_elements=scrollable,browser='Playwright Chromium',source='Actual isolated renderer page; no hand-built screenshot or new diagnostic panel')
  (O/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');browser.close()
 server.shutdown()
print(json.dumps(report,ensure_ascii=False))
