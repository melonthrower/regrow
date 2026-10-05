"""Drive the existing bounded step repeatedly; pause only after a settled round."""
import argparse
from itertools import count
import json
from pathlib import Path
from run_task_step import run_step, finalize_knowledge
from progress import CapturePaused


def run_session(root,run,out,mode,step=run_step):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    account={'mode':mode,'status':'running','http_started':0,'gui_started':0,'max_http':None,'max_gui_commands':None,'rounds':[]}
    manifest=Path(run)/'run_manifest.json'
    limits=json.loads(manifest.read_text()).get('session_limits',{}) if manifest.exists() else {}
    for key in ('max_http','max_gui_commands'):
        if limits.get(key) is not None:account[key]=int(limits[key])
    account['max_rounds']=int(limits['max_rounds']) if limits.get('max_rounds') is not None else None
    account['start_call']=int(json.loads(manifest.read_text()).get('last_call',0)) if manifest.exists() else 0
    pause=out.with_suffix('.pause')
    def save():
        account['end_call']=int(json.loads(manifest.read_text()).get('last_call',0)) if manifest.exists() else account['start_call']
        target=out/'session.json';temp=out/'session.tmp';temp.write_text(json.dumps(account,ensure_ascii=False,indent=2));temp.replace(target)
    save()
    for index in count():
        if account['max_rounds'] is not None and index>=account['max_rounds']:
            account['status']='round_limit';break
        if pause.exists():account['status']='paused_by_user';break
        # Reserve the existing round's full allowance; never exceed session limits.
        if any(account[limit] is not None and account[used]+6>account[limit]
               for used,limit in [('http_started','max_http'),('gui_started','max_gui_commands')]):
            account['status']='budget_limit';break
        folder=out/f'round-{index+1:04d}'
        try:step(root,run,folder)
        except CapturePaused:
            account['status']='paused_by_user'
            break
        except BaseException:
            account['status']='interrupted'
            raise
        finally:
            if (folder/'budget.json').exists():
                budget=json.loads((folder/'budget.json').read_text())
                account['http_started']+=budget['http_started'];account['gui_started']+=budget['gui_started']
            account['rounds'].append(str(folder.name));save()
        result=json.loads((folder/'result.json').read_text())
        if pause.exists():account['status']='paused_by_user';break
        if result['status']=='review_pending':
            account.update(status='review_pending',last_result='review_pending');break
        if mode=='step':account['status']='paused_after_step';break
        if result['status'] not in ('updated','paused_after_recovery_discovery','task_proposal','ready_next_round','repair_pending','task_deferred'):
            account.update(status='needs_review_or_complete',last_result=result['status']);break
    if (account.get('last_result') in ('scope_idle','region_complete') and mode=='auto'
            and not pause.exists() and (account['max_http'] is None or account['http_started']+6<=account['max_http'])):
        folder=out/'knowledge'
        try:
            result=finalize_knowledge(root,run,folder)
            account['knowledge_status']=result['status']
        except BaseException:
            account['status']='interrupted'
            raise
        finally:
            if (folder/'budget.json').exists():
                budget=json.loads((folder/'budget.json').read_text())
                account['http_started']+=budget['http_started'];account['gui_started']+=budget['gui_started']
            save()
    save();return account


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('output',type=Path);p.add_argument('mode',choices=['step','auto']);a=p.parse_args()
    run_session(Path(__file__).resolve().parent,a.run,a.output,a.mode)
