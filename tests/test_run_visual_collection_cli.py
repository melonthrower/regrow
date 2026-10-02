"""Current Region collection entry points; offline environments and model replies."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from gui_rewalk.run_visual_collection import build_parser, load_region_task, main
from tests.explore_fixtures import _png, _seed_ledger
from tests.test_stepwise_collection_graph import frozen_graph, instruction

ROOT=Path(__file__).resolve().parents[1]


def test_cli_help_describes_current_instruction_input():
    result=subprocess.run([sys.executable,str(ROOT/'gui_rewalk/run_visual_collection.py'),'--help'],capture_output=True,text=True)
    assert result.returncode==0
    assert '--instruction' in result.stdout and '--validate-only' in result.stdout
    assert '--graph ' not in result.stdout and '--region-ledger' not in result.stdout


def test_modular_ledger_validation_needs_no_model_or_environment(tmp_path,monkeypatch):
    from gui_rewalk.src.core.scenario import function_collection_research as f
    ledger=_seed_ledger();source=tmp_path/'ledger.json';ledger.save(source)
    task={**instruction(),'source_ledger':'ledger.json',
          'source_ledger_digest':hashlib.sha256(source.read_bytes()).hexdigest()}
    output=tmp_path/'instruction.json';output.write_text(json.dumps(task))
    monkeypatch.setattr(f,'build_region_model_agent',lambda *a: (_ for _ in ()).throw(AssertionError('No model during validation')))
    assert main(['--instruction',str(output),'--validate-only'])==0
    assert load_region_task(output)[2]==source


def test_invalid_instruction_stops_before_environment(tmp_path):
    path=tmp_path/'bad.json';path.write_text(json.dumps(instruction()))
    assert main(['--instruction',str(path),'--validate-only'])==2


def test_stepwise_cli_collects_with_guard_and_real_writer(tmp_path,monkeypatch,capsys):
    from gui_rewalk.src.core.scenario import function_collection_research as f
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    import gui_rewalk.src.core.app_lifecycle as lifecycle
    import gui_rewalk.src.core.explore.scope as scope_module
    source,_=frozen_graph(tmp_path);_,digest=load_collection_graph(source)
    task={**instruction(),'source_ledger':str(source),'source_ledger_digest':digest}
    path=tmp_path/'instruction.json';path.write_text(json.dumps(task));roles=[];delivered=[];closed=[]
    class Agent:
        def _call(self,**kw):
            roles.append(kw['role'])
            if kw['role']=='collection_grounding':return {'confirmed':True,'reason':'synthetic current target confirmed'}
            if kw['role']=='region_collection_final':return {'complete':True,'reason':'synthetic final goal observed'}
            done=bool(delivered)
            return {'app_scope':'target_app','visible_region_refs':['r1'],'region_visible':True,
                    'complete':done,'condition_value':None,'previous_action_outcome':'success' if done else 'none',
                    'reason':'Synthetic offline fixture','visual_target_ref':'r1.c1','action_intent':'Observe title',
                    'previous_action_observation':'Title is Draft' if done else '',
                    'previous_action_matches_intent':True if done else None,
                    'action':None if done else {'kind':'click','target':'Title','owner_ref':'',
                        'point_1000':[100,100],'text':None,'direction':None,'amount':None}}
    class Env:
        def __init__(self,**kw):pass
        def _get_obs(self):return {'screenshot':_png('blue')}
        def step(self,action,pause=0):delivered.append(action);return self._get_obs()
        def close(self):closed.append(True)
    monkeypatch.setattr(f,'build_region_model_agent',lambda *args:Agent())
    monkeypatch.setitem(sys.modules,'gui_rewalk.env.desktop_gui_gen_env',SimpleNamespace(DesktopGUIGenEnv=Env))
    monkeypatch.setattr(lifecycle,'DesktopWindowOwner',lambda env:None)
    monkeypatch.setattr(lifecycle,'launch_app',lambda *args,**kw:None)
    monkeypatch.setattr(lifecycle,'wait_for_app',lambda *args,**kw:True)
    monkeypatch.setattr(scope_module,'ScopeGuard',lambda **kw:SimpleNamespace(app_name='fixture',check=lambda:'target'))
    output=tmp_path/'collections'
    assert main(['--instruction',str(path),'--initial-app','fixture','--path-to-vm','offline.vmx',
                 '--output-root',str(output),'--max-turns','3'])==0
    summary=json.loads(capsys.readouterr().out)
    episode=Path(summary['episode_dir']);assert episode.is_relative_to(output/'runs')
    saved=json.loads((episode/'trajectory.json').read_text())
    assert closed and len(delivered)==1
    assert 'collection_grounding' in roles and roles[-1]=='region_collection_final'
    assert len(list((output/'runs').glob('*/matcher/source.json')))==1
    assert (episode/'screenshots').is_dir() and saved['meta']['final_frame']
    assert load_collection_graph(source)[1]==digest
