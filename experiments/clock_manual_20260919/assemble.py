"""Saved-frame prompt assembly prototype; no GUI execution or production ledger writes."""
import hashlib
import json
from pathlib import Path
from PIL import Image




def assemble(root, screenshot, source, history, execution):
    """source is capture provenance, not a model-inferred page or reset state.

    None means records not supplied; [] means the supplied record set is empty.
    Neither proves that no interaction ever occurred on the device.
    """
    if source not in {'live_capture', 'saved_frame'}:
        raise ValueError('source must describe capture provenance')
    for value in (history, execution):
        if value is not None and not isinstance(value, list):
            raise ValueError('record sets must be lists or None')
    root, screenshot = Path(root), Path(screenshot)
    raw = screenshot.read_bytes()
    with Image.open(screenshot) as img:
        width, height = img.size
        img.verify()
    stage = json.loads((root/'遍历prompt/流程/01_发现.json').read_text())
    texts = {name: (root/'遍历prompt'/name).read_text() for name in stage['parts']}
    schema_name = stage['schema']
    schema_text = (root/'遍历prompt'/schema_name).read_text()
    schema = json.loads(schema_text)
    def records(items):
        return {'status':'not_provided'} if items is None else {'status':'provided','items':items}
    dynamic = {
        'frame': {'ref':'current', 'source':source, 'width':width, 'height':height,
                  'sha256':hashlib.sha256(raw).hexdigest()},
        'history':records(history),
        'execution':records(execution),
    }
    return {
        'stage':stage['stage'],
        'system_prompt':'\n\n'.join(texts.values()),
        'user_prompt':json.dumps(dynamic, ensure_ascii=False, indent=2),
        'response_schema':schema,
        'parts':{k:hashlib.sha256(v.encode()).hexdigest()
                 for k,v in {**texts,schema_name:schema_text}.items()},
    }
