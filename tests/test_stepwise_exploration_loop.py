from tests.test_stepwise_deferral import setup
from tests.test_stepwise_region_tasks import tasks


def test_same_position_needs_three_observations(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    assert m.observe(run,'1') is None
    assert m.observe(run,'1') is None
    assert m.observe(run,'2') is None
    assert m.observe(run,'3')['repetitions']==3


def test_short_return_cycle_only_after_three_repeats(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(6):
        d.publish(run,'pos'+str(i),lambda r,s,*a:s.update(interactive_regions=['r1'] if i%2 else []))
        result=m.observe(run,str(i))
        assert (result is not None)==(i==5)
    assert result['cycle_length']==2


def test_progress_and_pending_execution_do_not_trigger(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    m.observe(run,'1');m.observe(run,'2')
    d.publish(run,'progress',lambda r,s,*a:r['r1']['tasks']['Policy'].update(status='done'))
    assert m.observe(run,'3') is None
    (run/'execution_pending.json').write_text('{}')
    assert m.observe(run,'4') is None


def test_changing_parameter_is_progress(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(4):
        d.publish(run,'value'+str(i),lambda r,s,*a:r['r1']['controls']['c1']['observations'][-1].update(state=str(i)))
        assert m.observe(run,str(i)) is None


def test_function_catalog_review_counts_as_progress(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    m.observe(run,'1');m.observe(run,'2')
    d.publish(run,'functions',lambda r,s,*a:r['r1'].update(function_inventory={'evidence_digest':'new-evidence'}))
    assert m.observe(run,'3') is None
    # A timestamp/call change alone is not new evidence.
    old=m.progress_key(d.load(run)[1])
    d.publish(run,'same',lambda r,s,*a:r['r1']['function_inventory'].update(source_call='another'))
    assert m.progress_key(d.load(run)[1])==old


def test_navigation_loop_ignores_observation_wording(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(6):
        def change(r,s,*args):
            s.update(interactive_regions=['elsewhere'] if i%2 else [],next_action_mode='explore',active_task=None)
            r['r1']['controls']['c1']['observations'][-1]['state']='visible wording '+str(i)
        d.publish(run,'nav'+str(i),change)
        result=m.observe(run,str(i))
    assert result and result['cycle_length']==2


def test_recovery_idle_loop_is_observed(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    d.publish(run,'recover',lambda r,s,*a:s.update(next_action_mode='review_result',interactive_regions=[]))
    for i in range(3):result=m.observe(run,str(i))
    assert result and result['repetitions']==3


def test_active_parent_task_keeps_child_parameter_progress(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(4):
        def change(r,s,*args):
            s.update(interactive_regions=['child'],active_task={'name':'edit parameter'})
            r['r1']['controls']['c1']['observations'][-1]['state']=str(i)
            r['r1']['tasks']['Policy']['findings']={'value':{'domain':{'type':'integer','values':[i]},'conditions':[]}}
        d.publish(run,'edit'+str(i),change)
        assert m.observe(run,str(i)) is None


def test_active_task_recovery_cycle_ignores_reworded_observations(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(6):
        def change(r,s,*args):
            s.update(interactive_regions=['r1'] if i%2 else [],
                     next_action_mode='explore' if i%2 else 'recover',
                     active_task={'region':'r1','name':'Policy'})
            r['r1']['controls']['c1']['observations'][-1]['state']='dialog recovered, wording '+str(i)
        d.publish(run,'recover-active'+str(i),change)
        result=m.observe(run,str(i))
    assert result and result['cycle_length']==2


def test_recovery_cycle_with_new_parameter_facts_is_progress(tmp_path):
    run,q,d=setup(tmp_path);m=tasks().helper('exploration_loop')
    for i in range(6):
        def change(r,s,*args):
            s.update(interactive_regions=['r1'] if i%2 else [],
                     next_action_mode='explore' if i%2 else 'recover',
                     active_task={'region':'r1','name':'Policy'})
            r['r1']['controls']['c1']['observations'][-1]['state']='wording '+str(i)
            r['r1']['tasks']['Policy']['findings']={'options':{
                'domain':{'type':'enum','values':list(range(i+1))},'conditions':[]}}
        d.publish(run,'recover-facts'+str(i),change)
        assert m.observe(run,str(i)) is None
