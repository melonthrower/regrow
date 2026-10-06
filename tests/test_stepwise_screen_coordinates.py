import importlib.util
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]/'experiments/clock_manual_20260919'

def module():
    spec=importlib.util.spec_from_file_location('locator',ROOT/'visual_region_locator.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_cropped_search_all_candidates_use_full_frame(tmp_path):
    rng=np.random.default_rng(3)
    template=rng.integers(0,255,(30,50,3),dtype=np.uint8)
    scene=np.zeros((300,400,3),dtype=np.uint8)
    scene[85:115,75:125]=template
    scene[185:215,225:275]=template
    t=tmp_path/'template.png';s=tmp_path/'screen.png'
    Image.fromarray(template).save(t);Image.fromarray(scene).save(s)
    locate=module().matcher()
    full=locate(t,s);local=locate(t,(s,(40,60,340,260)))
    assert tuple(local['box']) in {tuple(x['box']) for x in full['candidates']}
    assert {tuple(x['box']) for x in local['candidates']}=={tuple(x['box']) for x in full['candidates']}
    assert len(local['candidates'])>=2
    assert not local['accepted']  # Identical appearances still need identity review.


def test_discovery_discloses_historical_appearance(tmp_path):
    import locator
    from tests.test_recovery_discovery import seeded_run
    from tests.test_local_region_discovery import mod
    m=mod('discovery_step');run=seeded_run(tmp_path)
    m.await_discovery(run,'returned.png','return')
    def annotate(records,state,*args):
        for r in records.values():
            for c in r['controls'].values():
                c['observations'][-1]['icon_description']='distinct old appearance'
    m.publish(run,'appearance',annotate)
    q=locator.request_from_run(ROOT,run)
    import json
    rows=json.loads(q['user_prompt'])['本轮局部控件']
    assert rows and all(x['历史外观']=='distinct old appearance' for x in rows)
