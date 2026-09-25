import json
from copy import deepcopy
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'


def seed(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import region_graph as graph
    base=tmp_path/'knowledge_snapshots/v1'
    def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
    save(tmp_path/'knowledge_current.json',{'snapshot':'knowledge_snapshots/v1'})
    save(tmp_path/'run_manifest.json',{'app':'test.app'})
    save(base/'runtime_state.json',{'working_region':'a','interactive_regions':['a']})
    region={'id':'a','name':'菜单','description':'menu','controls':{'c':{'name':'设置','observations':[{'image':'crop.png'}]}},'tasks':{},'observations':[{'image':'crop.png'}],
      'actions':{'a1':{'control':'c','operation':'click','delivery':'executed_receipt_zero','interactive_regions':['b'],'result':{'exception':'none','description':'打开设置'}}},
      'transitions':[{'source_control':'c','target_region':'b','attempt':'a1'}]}
    save(base/'regions/a/region.json',region)
    save(base/'regions/b/region.json',{'id':'b','name':'设置页','controls':{},'tasks':{},'actions':{},'transitions':[]})
    from PIL import Image
    Image.new('RGB',(20,30)).save(base/'regions/a/crop.png')
    return graph,base,region,save


def test_graph_uses_observed_edges_and_keeps_external_results(tmp_path,monkeypatch):
    graph,base,r,save=seed(tmp_path,monkeypatch)
    r['actions']['external']={**deepcopy(r['actions']['a1']),'result':{'exception':'external_app','description':'浏览器'}}
    r['transitions'] += [{'source_control':'c','target_region':'b','attempt':'external'},{'source_control':'c','target_region':'b','attempt':'missing'},r['transitions'][0]]
    save(base/'regions/a/region.json',r)
    v=graph.project(tmp_path)
    assert len(v['edges'])==1 and v['edges'][0]['attempts']==['a1']
    assert len(v['nodes'][0]['controls'][0]['actions'])==2
    assert v['nodes'][0]['image'].startswith('/graph-image?')


def test_assets_only_resolve_registered_images_within_run(tmp_path,monkeypatch):
    graph,base,r,save=seed(tmp_path,monkeypatch)
    assert graph.asset(tmp_path,'knowledge_snapshots/v1','a','c').name=='crop.png'
    with pytest.raises(ValueError):graph.asset(tmp_path,'../outside','a')
    r['observations'][0]['image']='/etc/passwd';save(base/'regions/a/region.json',r)
    with pytest.raises(ValueError):graph.asset(tmp_path,'knowledge_snapshots/v1','a')


def test_graph_http_and_asset_routes(tmp_path,monkeypatch):
    graph,base,r,save=seed(tmp_path,monkeypatch)
    import progress_window,threading
    from urllib.request import urlopen
    app=progress_window.server(tmp_path,'http://127.0.0.1:1');threading.Thread(target=app.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{app.server_port}'
    try:
        with urlopen(origin+'/graph') as response:assert '区块跳转图' in response.read().decode()
        with urlopen(origin+'/graph.json') as response:v=json.load(response)
        with urlopen(origin+v['nodes'][0]['image']) as response:assert response.read().startswith(b'\x89PNG')
    finally:app.shutdown();app.server_close()
