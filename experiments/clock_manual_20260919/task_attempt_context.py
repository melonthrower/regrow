"""Task-history adapter; disclosure policy lives in history_context."""
import importlib.util
from pathlib import Path

def history():
    spec=importlib.util.spec_from_file_location('history_context',Path(__file__).with_name('history_context.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def describe(task,records):
    return history().attempts(task,records)
