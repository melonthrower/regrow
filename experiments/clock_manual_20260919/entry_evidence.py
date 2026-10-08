"""Disclose observed entry effects; task-result review decides applicability."""


def known_entries(region,control,operation):
    if operation not in ('tap','click'):return []
    hits=[]
    for aid,action in region.get('actions',{}).items():
        if (action.get('control')!=control or action.get('operation') not in ('tap','click')
                or action.get('delivery')!='executed_receipt_zero'
                or action.get('text_delivered') is False
                or action.get('result',{}).get('exception')!='none'
                or action.get('result',{}).get('returns_to_previous') is True):continue
        targets=list(dict.fromkeys(action.get('interactive_regions',[])))
        if len(targets)!=1 or targets[0]==region['id']:continue
        hits.append({'attempt':aid,'destination_region':targets[0],
                     'description':action['result'].get('description',''),
                     'conditions':action.get('entry_registration',{}).get('conditions',action.get('conditions',[]))})
    return hits


import importlib.util
from pathlib import Path

def history():
    spec=importlib.util.spec_from_file_location('history_context',Path(__file__).with_name('history_context.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def disclose(region,control,records):
    return history().disclose(region,control,records)

def related(region,control,records):
    return history().related(region,control,records)
