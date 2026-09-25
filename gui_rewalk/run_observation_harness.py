"""Bounded Luna frozen-image registration: tool harness or matched one-shot baseline."""
import argparse
import json
import time
from pathlib import Path
import requests
from gui_rewalk.src.core.evidence_explore.observation_harness import ObservationHarness, SYSTEM, BATCH_GUIDANCE
from gui_rewalk.src.core.explore.api_config import load_explore_api_config, local_explore_api_config_path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--goal',required=True);p.add_argument('--output',required=True)
    p.add_argument('--max-calls',type=int);p.add_argument('--one-shot',action='store_true')
    p.add_argument('--batch-inspection',action='store_true',help='Batch up to three crops; default two calls, reserving the final call for submission')
    p.add_argument('--batch-context',action='store_true',help='Also return a doubled neighboring view for each batch crop')
    a=p.parse_args()
    if a.batch_context and not a.batch_inspection:p.error('--batch-context requires --batch-inspection')
    if a.max_calls is None:a.max_calls=2 if a.batch_inspection else 4
    if a.one_shot and a.batch_inspection:p.error('--one-shot and --batch-inspection are separate conditions')
    if not 1<=a.max_calls<=8:p.error('--max-calls must be 1..8')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    h=ObservationHarness(Path(a.image).read_bytes(),out)
    cfg=load_explore_api_config(local_explore_api_config_path());http=[]
    def respond(history,tools):
        if len(http)>=a.max_calls:raise RuntimeError('HTTP budget exhausted')
        payload=dict(model='gpt-5.6-luna',instructions=SYSTEM+(BATCH_GUIDANCE if a.batch_inspection else '')+(' Each requested crop also returns a wider neighborhood marked context_for. Check it for alternative targets outside your initial guess.' if a.batch_context else ''),input=history,tools=tools,
            tool_choice='required',parallel_tool_calls=False,store=False,
            include=['reasoning.encrypted_content'],reasoning=dict(effort='medium'),max_output_tokens=6500,text=dict(verbosity='low'))
        # One-shot uses identical image/schema/model, with the inspect tool removed.
        row=dict(call=len(http)+1,started=time.time());http.append(row);h.write('http.json',http)
        h.write(f'request_{len(http):02}.json',payload)
        try:
            r=requests.post(cfg.base_url.rstrip('/')+'/responses',headers={'Authorization':'Bearer '+cfg.api_key},json=payload,timeout=cfg.timeout_seconds)
            row['status']=r.status_code
            body=r.json();row['usage']=body.get('usage');row['model']=body.get('model')
            safe=json.dumps(body,ensure_ascii=False).replace(cfg.base_url,'<endpoint>')
            if cfg.api_key:safe=safe.replace(cfg.api_key,'<redacted>')
            h.write(f'response_{len(http):02}.json',json.loads(safe))
            if r.status_code!=200:raise RuntimeError(f'HTTP {r.status_code}; see sanitized response')
            if body.get('status') not in (None,'completed'):raise RuntimeError('incomplete model response')
            return body.get('output',[])
        finally:row['seconds']=time.time()-row['started'];h.write('http.json',http)
    h.write('condition.json',dict(model='gpt-5.6-luna',reasoning='medium',goal=a.goal,one_shot=a.one_shot,batch_inspection=a.batch_inspection,batch_context=a.batch_context,max_calls=1 if a.one_shot else a.max_calls,gui_actions=0))
    try:
        result=h.run((lambda history,tools:respond(history,[t for t in tools if t['name']=='update_inventory'])) if a.one_shot else respond,
                     a.goal+(' Submit the complete inventory in this single call, commit=true.' if a.one_shot else ''),max_calls=1 if a.one_shot else a.max_calls,batch_inspection=a.batch_inspection,batch_context=a.batch_context)
    except Exception as exc:
        # Transport exceptions may contain private endpoints; retain only the class.
        result=dict(status='transport_error',error_type=type(exc).__name__,calls=len(http),report=None)
    h.write('result.json',result);print(json.dumps(dict(status=result['status'],calls=result['calls']),ensure_ascii=False))
    if result['status']!='submitted':raise SystemExit(1)


if __name__=='__main__':main()
