"""Render an exploration goal and recorded attempts, without prescribing a solution."""

import importlib.util
from pathlib import Path

def history():
    spec=importlib.util.spec_from_file_location('history_context',Path(__file__).with_name('history_context.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def known_findings(records,state,task_region,name,task):
    return history().findings(records,state,task_region,name,task)

def build(records,state,task_region,name,task):
    return history().action_context(records,state,task_region,name,task)
