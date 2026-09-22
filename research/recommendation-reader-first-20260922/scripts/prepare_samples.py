"""Copy fixed, necessary historical inputs. No model request or production mutation."""
import argparse,json,shutil,sys,difflib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--production',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
P=a.production.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
def copy(src,dst):
    src=P/src; dst=out/dst;dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_dir():
        for f in src.rglob('*'):
            if f.is_file():copy(f.relative_to(P),dst.relative_to(out)/f.relative_to(src))
    else:shutil.copy2(src,dst)
def save(name,obj):
    q=out/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
D=Path('local_archive/ai_tasks/nightly/rerun-2026-09-21/recommendation')
old=Path('.worktrees/recommendation-authoring-20260918/local_archive/ai_tasks/normal-authoring-20260921-074913/normal-root/local_archive/ai_tasks/nightly/rerun-2026-09-21/recommendation')
records={}
for key,folder,code in [('D1',D,'300398.SZ'),('H1',D,'301589.SZ'),('H2',D,'001378.SZ'),('H3',Path('local_archive/ai_tasks/nightly/rerun-2026-09-22/recommendation'),'300658.SZ')]:
    packet=folder/'articles'/f'{code}-packet.json'
    copy(packet,f'{key}/packet.json')
    data=json.loads((P/packet).read_text());records[key]={'identity':data['identity'],'source':str(packet),'used_for_tuning':key=='D1','article_read_for_tuning':False}
    copy(folder/'writing-material.json',f'{key}/materials.json')
copy(D/'articles/300398.SZ/author-300398-SZ-files-2/input','D1/original-author-input')
copy(D/'articles/300398.SZ/author-300398-SZ-files-2/output/article.md','C2/article.md')
copy(D/'articles/300398.SZ-packet.json','C2/packet.json')
for name in ('current-opinion-before-owners.json','current-opinion-owner-selection-answer.json','current-opinion-owner-monitor-answer.json','selection-handoff.json'):
    copy(D/name,'D2/'+name)
copy(D/'articles/300398.SZ/author-300398-SZ-files-2/input/prior-article.md','D2/prior-article.md')
copy(D/'articles/300398.SZ/author-300398-SZ-files-2/input/revision-issues.json','D2/revision-issues.json')
copy(old/'articles/300398.SZ/author-300398-SZ-files-1/output/article.md','C1/article.md')
copy(old/'articles/300398.SZ/author-300398-SZ-files-1/input/packet.json','C1/packet.json')
copy(old/'articles/300398.SZ/author-300398-SZ-files-1/input/research-handoff.md','C1/research-handoff.md')
copy(old/'articles/300398.SZ/author-300398-SZ-files-1/input','C1/original-author-input')
C3=Path('local_archive/ai_tasks/writing-trials/20260918-181714')
copy(C3/'runs/repeat-1/600522-SH/author-600522-SH-article.md','C3/article.md')
copy(C3/'input/packets/600522.SH.json','C3/packet.json')
copy(Path('.worktrees/recommendation-authoring-20260918/local_archive/ai_tasks/business-closeout-20260921-181805/closing-root/local_archive/ai_tasks/nightly/closeout-2026-09-21/recommendation/current-opinion-owner-selection-answer.json'),'withdrawal/owner-selection-answer.json')
# H3 historical upstream only; no accepted state installed into active paths.
folder=Path('local_archive/ai_tasks/nightly/rerun-2026-09-22/recommendation')
for name in ('accepted-recommendation.json','selection-handoff.json','research-reply.md'):
    copy(folder/name,'H3/upstream/'+name)
copy(Path('local_archive/ai_tasks/state/nightly-rerun-2026-09-22.json'),'H3/upstream/state.json')
records['D2']={**records['D1'],'source':str(D/'articles/300398.SZ/author-300398-SZ-files-2/input'),'substitution_reason':'捷捷微电实际最终撤回；固定使用飞凯同一真实修订，不能制造有效捷捷推荐。D1/D2重合是限制。'}
for key in ('C1','C2','C3'):
    records[key]={'identity':json.loads((out/key/'packet.json').read_text())['identity'],'source':str(old if key=='C1' else D if key=='C2' else C3),'reference_label':{'C1':'user_approved','C2':'user_difficult','C3':'reference_label_unconfirmed'}[key]}
save('sample-manifest.json',records)
print(json.dumps({k:v['identity'] for k,v in records.items()},ensure_ascii=False,indent=2))
