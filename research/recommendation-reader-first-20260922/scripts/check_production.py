"""Read-only comparison against the small recorded production inventory."""
import argparse,datetime,hashlib,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--production',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args();R=a.production.resolve();E=a.evidence.resolve();before=json.loads((E/'production-before.json').read_text())
files=[];changes=[]
for old in before['files']:
 path=Path(old['path'].replace('$PRODUCTION_ROOT',str(R)).replace('$USER_HOME',str(Path.home())))
 if path.is_file():
  now={'path':old['path'],'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 else:now={'path':old['path'],'missing':True}
 files.append(now)
 if now!=old:changes.append({'before':old,'after':now})
label='com.ccrt.stock-analysis-assistant.ai-nightly';domain='gui/'+str(os.getuid())
loaded=subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True,text=True).returncode==0
disabled=subprocess.run(['launchctl','print-disabled',domain],capture_output=True,text=True)
import re
match=re.search(r'\"'+re.escape(label)+r'\"\s*=>\s*(disabled|enabled|true|false)\b',disabled.stdout)
is_disabled=match.group(1) in ('disabled','true') if match else 'unknown'
git=lambda *v:subprocess.check_output(['git',*v],cwd=R,text=True).strip()
value={'observed_at':datetime.datetime.now().astimezone().isoformat(),'nightly':{'label':label,'loaded':loaded,'disabled':is_disabled,'disabled_query_exit_code':disabled.returncode,'disabled_record':match.group(0) if match else 'not_found'},'files':files,'changes':changes,'production_branch':git('branch','--show-current'),'production_head':git('rev-parse','HEAD'),'production_status':git('status','--short'),'inventory_unchanged':not changes,'scope':'Same 37-path targeted inventory as before; not a hash of the entire warehouse'}
(E/'production-after.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:value[k] for k in ('nightly','production_branch','production_head','inventory_unchanged')}))
