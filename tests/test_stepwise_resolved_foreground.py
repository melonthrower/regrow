from tests.test_local_region_discovery import mod, records


def test_legacy_pixel_containment_resolution_does_not_confirm_identity(tmp_path):
    m=mod('visual_region_locator');rs=records(2)
    frame=tmp_path/'frame.png';frame.write_bytes(b'frame')
    resolved={'focus':'r0','status':'resolved','frame_path':str(frame.resolve()),'region':'r1'}
    plan=m.plan(rs,'r0',frame,foreground_resolution=resolved,
                locate=lambda *a:{'accepted':True,'box':[0,0,20,20],'score':1})
    assert plan['mode']=='relocate' and plan['foreground_check'] is None


def test_force_relocation_does_not_use_cached_boundary(monkeypatch):
    m=mod('visual_region_locator');rs=records(1)
    row=dict(region='r0',strong=False,bounds=None,anchors=[],whole={'accepted':False},matched_controls=0)
    monkeypatch.setattr(m.history,'scan',lambda *a,**k:[row])
    plan=m.plan(rs,'r0','frame',force_relocate=True,
        foreground={'region_bounds':{'r0':[0,0,100,100]}})
    assert plan['mode']=='relocate' and plan['regions'][0]['bounds'] is None
