"""Request-local image provenance, supplied by the builder that owns the frame.

Builders own frame time. Saved updates can be read by their explicit old contract.
"""

def label(request, frame, purpose):
    request.setdefault('frame_context', {})[str(frame)] = purpose
    return request

def purpose(request, frame):
    return request.get('frame_context', {}).get(str(frame), '原请求未标注时点；结合原图片说明，不推断为当前图')

def roles(request):
    return [{'图片': i, '用途': purpose(request, frame)} for (i, frame) in enumerate(request.get('screenshots', []), 1)]

def primary(request):
    """Read the stage's evidence frame, including saved pre-single-frame updates."""
    frames = request.get('screenshots') or request.get('image_refs') or []
    if not frames:
        return None
    if len(frames) == 1 or request.get('role') == 'control_identity_comparison':
        return frames[0]
    original = request.get('original_request', request)
    if original.get('role') == 'observation_update' or original.get('pipeline_step') == 'update':
        return original['screenshots'][1]
    raise ValueError('多图请求缺少明确的阶段选图合同')

def select(request, frame, purpose_text=None):
    """The producing stage explicitly selects its one original image."""
    request['screenshots'] = [str(frame)] if frame is not None else []
    request['image_refs'] = list(request['screenshots'])
    if frame is not None and purpose_text is not None:
        label(request, str(frame), purpose_text)
    return request

def validate(request):
    count = max(len(request.get('screenshots', [])), len(request.get('image_refs', [])))
    if count > 2:
        raise ValueError('比较最多使用两张原图，由步骤明确选择')
    if count == 2:
        from regrow.prompts.output import fields
        geometry = {'bbox', 'icon_bbox', 'click_bbox', 'click_area', 'x', 'y', 'end_x', 'end_y', 'left', 'top', 'right', 'bottom'}
        if 'response_schema' not in request or geometry.intersection(fields(request['response_schema'])):
            raise ValueError('两图比较不能要求输出坐标或bbox；定位与几何登记使用单图')
