"""Shared final request preparation, evidence persistence, budget and model send.

Used by both normal steps and recovery, on Android and desktop.
"""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from register_update import read, write_json
import progress


class BudgetExhausted(ValueError):
    """A normal stop at the caller's accounting boundary, without new delivery."""


def with_environment_scope(root,request):
    """The traversal environment restriction applies to both GUI platforms."""
    # This repair can edit a sharing relation only; it has no GUI action output.
    if request.get('original_request',{}).get('stage')=='shared_control_review':return request
    request=deepcopy(request)
    path='平台/遍历环境只读.prompt'
    if not any(part['path']==path for part in request['fixed_parts']):
        text=(Path(root)/'遍历prompt'/path).read_text()
        request['fixed_parts'].append({'path':path,'text':text})
        request['system_prompt']+='\n\n'+text
    return request



def with_run_scope(request,run):
    manifest=Path(run)/'run_manifest.json'
    scope=read(manifest).get('exploration_scope') if manifest.exists() else None
    if not scope:return request
    block='\n\n本轮遍历允许范围（运行发起者提供，不由任务生成扩大）：\n'+scope
    if block in request['user_prompt']:return request
    request=deepcopy(request)
    request['user_prompt']+=block
    return request



def with_frame_context(request,run):
    """Disclose source dimensions; never infer them from model image rendering."""
    from PIL import Image
    request=deepcopy(request)
    lines=[]
    for index,frame in enumerate(request.get('screenshots',[]),1):
        with Image.open(Path(run)/frame) as image:width,height=image.size
        lines.append(f'第{index}张：{width}×{height} 像素；框边界 0≤left<right≤{width}，0≤top<bottom≤{height}。')
    if lines:
        block='\n\n截图坐标说明（按图片发送顺序）：\n'+'\n'.join(lines)+'\n坐标使用对应原图像素；显示缩放不改变坐标范围，不要猜测设备分辨率。'
        if block not in request['user_prompt']:request['user_prompt']+=block
    return request



class ModelTransport:
    """Run adapters supply root, run, account, ledger and save()."""

    def call(self,request):
        from action_commands import platform_request
        request=platform_request(request,getattr(self,"platform","android"))
        from task_prerequisites import augment
        request=augment(self.root,self.run,request)
        request=with_environment_scope(self.root,request)
        request=with_run_scope(request,self.run)
        request=with_frame_context(request,self.run)
        from history_disclosure import project
        request=project(request)
        # Pending requests may predate required-field declarations. Keep original
        # evidence immutable and make the newly sent schema strict-compatible.
        def strict_fields(schema):
            if isinstance(schema,list):
                for child in schema:strict_fields(child)
            elif isinstance(schema,dict):
                for key in ('controls_complete','returns_to_previous'):
                    if key in schema.get('properties',{}) and key not in schema.get('required',[]):
                        schema.setdefault('required',[]).append(key)
                for child in schema.values():strict_fields(child)
        strict_fields(request['response_schema'])
        progress.request(request)
        if self.account['http_started']>=self.account['max_http']:raise BudgetExhausted('HTTP budget exhausted')
        number=max([int(p.name) for p in (self.run/'calls').iterdir() if p.name.isdigit()]+[0])+1
        call=f'{number:04d}';folder=self.run/'calls'/call;folder.mkdir()
        write_json(folder/'request.json',request);write_json(folder/'response.schema.json',request['response_schema'])
        (folder/'system.prompt').write_text(request['system_prompt']);(folder/'user.prompt').write_text(request['user_prompt'])
        for part in request['fixed_parts']:
            path=folder/'fixed'/part['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(part['text'])
        self.account['http_started']+=1;self.save()
        manifest=read(self.run/'run_manifest.json');manifest['actual_model_calls']+=1;manifest['last_call']=call
        write_json(self.run/'run_manifest.json',manifest)
        from exploration_summary import record
        record(self.run,folder,request,self.ledger.parent)
        result=subprocess.run([sys.executable,str(self.run/'call_once.py'),call],capture_output=True,timeout=210)
        (folder/'transport.log').write_bytes(result.stdout+result.stderr)
        result.check_returncode()
        progress.detail('回复已收到，框架校验与登记中')
        return call,read(folder/'response.json')
