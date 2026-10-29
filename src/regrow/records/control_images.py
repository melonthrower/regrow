"""Reuse identical control appearances despite different crop padding."""
import hashlib
from pathlib import Path


def fingerprint(image):
    from PIL import Image, ImageChops
    pixels = image.convert('RGB')
    color = pixels.getpixel((0, 0))
    corners = [(pixels.width - 1, 0), (0, pixels.height - 1),
               (pixels.width - 1, pixels.height - 1)]
    if all(pixels.getpixel(p) == color for p in corners):
        bounds = ImageChops.difference(pixels, Image.new('RGB', pixels.size, color)).getbbox()
        if bounds:
            pixels = pixels.crop(bounds)
    return hashlib.sha256(str(pixels.size).encode() + pixels.tobytes()).hexdigest()


def existing(record, pixels, snapshot):
    from PIL import Image
    from regrow.records.object_store import observation_history
    from regrow.recognition.identity_templates import usable
    signature = fingerprint(pixels)
    for row in reversed(observation_history(record)):
        if not usable(row):
            continue
        path = Path(snapshot) / row['image']
        if path.is_file():
            with Image.open(path) as old:
                if fingerprint(old) == signature:
                    return row['image']
    return None


def images(record):
    """Public appearance references; full control crops, with real state conditions."""
    from copy import deepcopy
    from regrow.records.object_store import observation_history
    from regrow.recognition.identity_templates import usable
    result = []
    history = observation_history(record)
    declared = [] if any(row.get('image') for row in history) else record.get('image', [])
    if isinstance(declared, str):
        declared = [{'path': declared, 'conditions': []}]
    for entry in declared or []:
        if isinstance(entry, dict) and entry.get('path') and not any(v['path'] == entry['path'] for v in result):
            result.append({'path': entry['path'], 'conditions': list(entry.get('conditions', []))})
    for row in history:
        if not usable(row):
            continue
        entry = {'path': row['image'], 'conditions': list(row.get('image_conditions', []))}
        previous = next((v for v in result if v['path'] == entry['path']), None)
        if previous is None:
            result.append(entry)
        elif entry['conditions']:
            previous['conditions'] = entry['conditions']
    return deepcopy(result)


def label_appearances(records, snapshot, labels):
    """Apply reviewed state labels to the original image observation in a commit."""
    from regrow.records.object_store import control_record, observation_history
    for label in labels:
        control = control_record(records, label['control'])
        found = False
        for row in observation_history(control):
            if row.get('image') and (Path(snapshot) / row['image']).resolve() == Path(label['image']).resolve():
                row['image_conditions'] = [label['state']]
                row['image_conditions_evidence'] = {'source_call': label['source_call'], 'reason': label['reason']}
                found = True
        if not found:
            raise ValueError('已比较的历史外观不存在，不能把状态说明写到其他图片上')
        control['image'] = images(control)
