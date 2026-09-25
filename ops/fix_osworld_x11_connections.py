"""Close per-request X11 connections in OSWorld guest size and screenshot routes."""
from pathlib import Path
import argparse


OLD = '''        d = display.Display()
        screen_width = d.screen().width_in_pixels
        screen_height = d.screen().height_in_pixels'''
NEW = '''        d = display.Display()
        try:
            screen_width = d.screen().width_in_pixels
            screen_height = d.screen().height_in_pixels
        finally:
            d.close()'''
CURSOR_OLD = '''        cursor_obj = Xcursor()
        imgarray = cursor_obj.getCursorImageArrayFast()'''
CURSOR_NEW = '''        cursor_obj = Xcursor()
        if not cursor_obj.display:
            raise RuntimeError("Cannot connect screenshot cursor to X11")
        try:
            imgarray = cursor_obj.getCursorImageArrayFast()
        finally:
            cursor_obj.xlib.XCloseDisplay(cursor_obj.display)'''


def patch_source(source: str) -> str:
    for name, old, new in [('screen-size', OLD, NEW), ('cursor', CURSOR_OLD, CURSOR_NEW)]:
        if new in source:
            continue
        if source.count(old) != 1:
            raise ValueError(f'Expected exactly one unpatched Linux {name} block')
        source = source.replace(old, new, 1)
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server_source', type=Path)
    path = parser.parse_args().server_source
    original = path.read_bytes()
    source = original.decode('utf-8')
    patched = patch_source(source)
    if patched == source:
        print('already patched')
    else:
        backup = path.with_name(path.name + '.before-x11-close')
        compile(patched, str(path), 'exec')
        with backup.open('xb') as stream:
            stream.write(original)
        path.write_text(patched, encoding='utf-8')
        print('patched; original saved to', backup)
