"""Working versions freeze edited modules and preserve original context provenance."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
import prompt_review_work as work

class Store:
    def __init__(self):self.text='old';self.paths={'a.prompt':True}
    def read(self,name):return {'text':self.text}

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(work.trace,'trace',lambda r,k:{'id':k,'calls':['01','02']})
    monkeypatch.setattr(work.trace,'overview',lambda r:[{'id':'case','steps':[{'call':'01','role':'observation','modules':['a.prompt']},{'call':'02','role':'action_selection','modules':[]}]}])
    return tmp_path,Store()

def test_version_is_frozen_and_reports_dirty_modules(setup):
    root,store=setup
    first=work.save(root,{'trace':'case','parent':None,'modules':['a.prompt']},store)
    ident=first['revision']['id'];store.text='new'
    assert work.view(root,'case',store)['unsaved_modules']==['a.prompt']
    second=work.save(root,{'trace':'case','parent':ident,'modules':['a.prompt']},store)
    assert second['revision']['modules']['a.prompt']=='new'
    assert work.trace.read(work.folder(root,'case')/'revisions'/ident/'revision.json')['modules']['a.prompt']=='old'
    assert [s['affected'] for s in second['steps']]==[True,False]
    with pytest.raises(ValueError):work.save(root,{'trace':'case','parent':ident},store)

def test_context_cannot_change_original_frame(setup,monkeypatch):
    root,store=setup
    base={'snapshot':'s','regions':{},'state':{'pending_frame':'old.png'}}
    monkeypatch.setattr(work.trace,'step',lambda *a:{'before':base})
    with pytest.raises(ValueError,match='截图来源'):
        work.validate_context(root,'case','01',{**base,'state':{'pending_frame':'fake.png'}})

def test_batch_rejects_unfrozen_module_change(setup):
    root,store=setup
    v=work.save(root,{'trace':'case','parent':None,'modules':['a.prompt']},store)
    store.text='changed without saving'
    with pytest.raises(ValueError,match='尚未收录'):
        work.batch_start(root,{'trace':'case','revision':v['revision']['id'],'mode':'preview'},store)

def test_adoption_preserves_modules_and_same_value_new_provenance(setup,monkeypatch):
    root,store=setup
    monkeypatch.setattr(work,'validate_context',lambda r,k,c,v:v)
    first=work.save(root,{'trace':'case','parent':None,'modules':['a.prompt'],'contexts':{'01':{'value':1}}},store)['revision']
    store.text='uncollected edit'
    second=work.save(root,{'trace':'case','parent':first['id'],'contexts':{'01':{'value':1}}},store,
       provenance={'kind':'adopted_registration','dependency_job':'j1'},module_texts=first['modules'])['revision']
    assert second['id']!=first['id']
    assert second['modules']=={'a.prompt':'old'}
    assert second['context_sources']['01']['dependency_job']=='j1'
    assert work.view(root,'case',store)['unsaved_modules']==['a.prompt']

def test_downstream_stale_survives_batch_until_context_updated(setup,monkeypatch):
    root,store=setup
    monkeypatch.setattr(work,'validate_context',lambda r,k,c,v:v)
    v=work.save(root,{'trace':'case','parent':None,'modules':[]},store)['revision']
    dest=work.folder(root,'case')/'batches/b1'
    work.trace.write(dest/'revision.json',v)
    work.trace.write(dest/'status.json',{'mode':'test','steps':[{'call':'01','downstream':'state changed'}]})
    assert work.view(root,'case',store)['steps'][1]['stale']
    work.save(root,{'trace':'case','parent':v['id'],'contexts':{'02':{'state':'new'}}},store)
    assert not work.view(root,'case',store)['steps'][1]['stale']

def test_failed_launch_marks_downstream_across_batches(setup,monkeypatch):
    root,store=setup
    import prompt_review_editor
    monkeypatch.setattr(prompt_review_editor,'EditorStore',lambda root:store)
    monkeypatch.setattr(work.trace,'step',lambda *a:{'replayable':True,'modules':[],'request':{'role':'observation'}})
    def fail(*a,**k):raise ValueError('cannot reconstruct')
    monkeypatch.setattr(work.trace,'start',fail)
    v=work.save(root,{'trace':'case','parent':None,'modules':[]},store)['revision']
    dest=work.folder(root,'case')/'batches/fail'
    work.trace.write(dest/'revision.json',v)
    work.trace.write(dest/'status.json',{'id':'fail','trace':'case','mode':'test','status':'running','steps':[{'call':'01','status':'pending'},{'call':'02','status':'pending'}],'calls':0})
    work.run_batch(root,dest)
    assert work.trace.read(dest/'status.json')['steps'][1]['status']=='stale'
    assert work.view(root,'case',store)['steps'][1]['stale']

def test_current_display_rejects_old_revision_dirty_draft_and_changed_source(setup,monkeypatch):
    root,store=setup
    monkeypatch.setattr(work.trace,'step',lambda *a:{'modules':['a.prompt']})
    version=work.save(root,{'trace':'case','parent':None,'modules':['a.prompt']},store)['revision']
    source=root/'source';source.mkdir();(source/'code.py').write_text('old code')
    monkeypatch.setattr(work.trace,'SOURCE',source)
    dest=root/'trace_jobs/j1'
    work.trace.write(dest/'status.json',{'id':'j1','trace':'case','call':'01','status':'preview_ready'})
    work.trace.write(dest/'job.json',{'revision':'wrong'})
    work.trace.write(dest/'preview.json',{'system_prompt':'assembled'})
    work.trace.write(dest/'source-manifest.json',{'code.py':work.hashlib.sha256(b'old code').hexdigest()})
    assert work.current_display(root,'case','01',store)['preview'] is None
    work.trace.write(dest/'job.json',{'revision':version['id']})
    assert work.current_display(root,'case','01',store)['preview']['system_prompt']=='assembled'
    store.text='new draft'
    assert work.current_display(root,'case','01',store)['preview'] is None
    store.text='old';(source/'code.py').write_text('new code')
    assert work.current_display(root,'case','01',store)['preview'] is None
