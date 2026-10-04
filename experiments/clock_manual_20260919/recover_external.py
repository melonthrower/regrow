"""Run only the current external recovery episode, then pause. Android adapter."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from register_update import read, write_json

import progress


# Shared send helpers remain directly importable for existing callers.
from model_transport import ModelTransport, with_environment_scope, with_run_scope, with_frame_context


ADB='/data/shenghonghui/android-sdk/platform-tools/adb'


class RecoveryRun(ModelTransport):
    def __init__(self, root, run):
        self.root,self.run=Path(root),Path(run).resolve()
        self.manifest=read(self.run/'run_manifest.json')
        self.device=self.manifest['device'];self.package=self.manifest['app']
        self.ledger=self.run/'recovery_execution.json'
        if self.ledger.exists():raise ValueError('recovery execution already exists; inspect pending evidence before resuming')
        self.account={'max_http':6,'max_gui_commands':4,'http_started':0,'gui_started':0,'status':'running','attempts':[]}
        self.save()

    def save(self):write_json(self.ledger,self.account)

    def adb(self, argv):
        if argv[:2]==['shell','input']:progress.detail('执行设备动作：'+argv[2])
        elif argv[:3]==['shell','am','force-stop']:progress.detail('重启目标应用，保留数据')
        return subprocess.run([ADB,'-s',self.device,*argv],capture_output=True,timeout=30)

    def screenshot(self,path):
        result=self.adb(['exec-out','screencap','-p'])
        result.check_returncode();path.write_bytes(result.stdout)
        from desktop_capture import publish_frame
        publish_frame(getattr(self,'run',None),path,'adb')

    def state(self):
        snapshot=self.run/read(self.run/'knowledge_current.json')['snapshot']
        state=read(snapshot/'runtime_state.json')
        if (snapshot/'recovery.json').exists():episode=read(snapshot/'recovery.json')
        else:
            if state['next_action_mode'] not in ('recover','recover_scope'):raise ValueError('no committed external-app recovery')
            ref=state['last_action_result'];episode={'trigger_attempt':ref['action'],'trigger_region':ref['region'],'working_region':state['working_region'],'actions':[]}
        records={p.parent.name:read(p) for p in (snapshot/'regions').glob('*/region.json')}
        return episode,records


    def run_episode(self):
        import recover_loop
        with progress.round_status(self.run,self.ledger.parent):
            result=recover_loop.run(self.root,self,self.ledger.parent,self.call)
        self.account['status']=result['status'];self.save();return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    runner=RecoveryRun(Path(__file__).resolve().parent,args.run)
    try:runner.run_episode()
    except BaseException:
        runner.account['status']='interrupted_inspect_pending';runner.save();raise
    print(json.dumps(runner.account,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
