from types import SimpleNamespace

import pytest

from ops.fix_osworld_x11_connections import OLD, CURSOR_OLD, patch_source


SOURCE = 'def get_screen_size():\n    if platform_name == "Linux":\n' + OLD + '''
    return {"width": screen_width, "height": screen_height}
'''
SOURCE += '\ndef capture_screen_with_cursor():\n    if platform_name == "Linux":\n' + CURSOR_OLD + '''
        return imgarray
'''


@pytest.mark.parametrize('fails', [False, True])
def test_screen_size_connection_is_closed_on_success_and_failure(fails):
    closed = []

    def screen():
        if fails:
            raise RuntimeError('X11 read failed')
        return SimpleNamespace(width_in_pixels=1280, height_in_pixels=800)

    connection = SimpleNamespace(screen=screen, close=lambda: closed.append(True))
    namespace = {'platform_name': 'Linux', 'display': SimpleNamespace(Display=lambda: connection)}
    exec(patch_source(SOURCE), namespace)
    if fails:
        with pytest.raises(RuntimeError, match='X11 read failed'):
            namespace['get_screen_size']()
    else:
        assert namespace['get_screen_size']() == {'width': 1280, 'height': 800}
    assert closed == [True]


@pytest.mark.parametrize('fails', [False, True])
def test_screenshot_cursor_connection_is_closed_on_success_and_failure(fails):
    closed = []

    def pixels():
        if fails:
            raise RuntimeError('Cursor read failed')
        return 'copied pixels'

    cursor = SimpleNamespace(display=42, getCursorImageArrayFast=pixels,
        xlib=SimpleNamespace(XCloseDisplay=lambda handle: closed.append(handle)))
    namespace = {'platform_name': 'Linux', 'Xcursor': lambda: cursor}
    exec(patch_source(SOURCE), namespace)
    if fails:
        with pytest.raises(RuntimeError, match='Cursor read failed'):
            namespace['capture_screen_with_cursor']()
    else:
        assert namespace['capture_screen_with_cursor']() == 'copied pixels'
    assert closed == [42]


def test_null_cursor_connection_is_not_used():
    cursor = SimpleNamespace(display=None)
    namespace = {'platform_name': 'Linux', 'Xcursor': lambda: cursor}
    exec(patch_source(SOURCE), namespace)
    with pytest.raises(RuntimeError, match='Cannot connect'):
        namespace['capture_screen_with_cursor']()


def test_patch_does_not_duplicate_cleanup_or_touch_an_unexpected_server():
    patched = patch_source(SOURCE)
    assert patch_source(patched) == patched
    with pytest.raises(ValueError, match='exactly one'):
        patch_source('def different_route(): pass\n')
