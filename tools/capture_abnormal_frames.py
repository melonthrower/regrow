#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Capture REAL abnormal-state frames from the docker desktop VM, to test the
crash_dialog / desktop_blank axes of the VLM abnormal-detection prompt that the
132-frame replay never exercised (that set was all wrong_app).

The user's actual concern is "应用异常关闭" (app closed/crashed), whose strongest
real signal is: the app is gone and we are back at the bare desktop. We produce
that for real (launch an app, then kill it), plus controls:

  gimp   normal      none          running     -> normal   (control: app alive)
  gimp   abnormal    desktop_blank killed      -> abnormal (THE crash case)
  desktop abnormal   desktop_blank allclosed   -> abnormal (bare desktop)
  evince normal      none          errordialog -> normal   (control: in-app
                                                  error dialog is NOT a crash;
                                                  guards against crash_dialog
                                                  over-triggering)

Saved as /tmp/abn_frames/<app>__<expected_status>__<expected_kind>__<tag>.png

Run on js1:
    cd /data/shenghonghui/GUI-ReWalk-mobile
    PYTHONPATH=.:OSWorld python tools/capture_abnormal_frames.py
"""

import os
import time

OUT = "/tmp/abn_frames"


def save(env, name):
    obs = env._get_obs()
    ss = obs.get("screenshot", b"") if isinstance(obs, dict) else b""
    if not ss:
        print(f"[warn] no screenshot for {name}")
        return False
    path = os.path.join(OUT, name)
    with open(path, "wb") as f:
        f.write(ss)
    print(f"[saved] {name} ({len(ss)} bytes)")
    return True


def main():
    os.makedirs(OUT, exist_ok=True)
    from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
    from gui_rewalk.src.core.app_lifecycle import (
        _close_all_windows, launch_app, _run_vm_command)

    env = DesktopGUIGenEnv(
        provider_name="docker", path_to_vm="/tmp/System.qcow2",
        action_space="gen_data", screen_size=(1920, 1080), headless=False,
        os_type="Ubuntu")
    print("[boot] resetting env ...")
    env.reset()
    time.sleep(3)

    # 1) bare desktop: close everything that opened in init_state
    try:
        _close_all_windows(env)
        time.sleep(2.5)
        save(env, "desktop__abnormal__desktop_blank__allclosed.png")
    except Exception as e:
        print(f"[err] allclosed: {e}")

    # 2) normal app: launch GIMP
    try:
        launch_app(env, "GNU image")
        time.sleep(6)
        save(env, "gimp__normal__none__running.png")
    except Exception as e:
        print(f"[err] gimp launch: {e}")

    # 3) THE crash case: kill GIMP mid-use -> back to bare desktop
    try:
        _run_vm_command(env, ["pkill", "-9", "-f", "gimp"], timeout=10)
        time.sleep(3)
        save(env, "gimp__abnormal__desktop_blank__killed.png")
    except Exception as e:
        print(f"[err] gimp kill: {e}")

    # 4) control: in-app error dialog (evince on a non-PDF) — app is ALIVE,
    #    so this must stay 'normal'; it guards against crash_dialog over-firing.
    try:
        _run_vm_command(env, ["bash", "-lc",
                              "printf 'this is not a pdf\\n' > /tmp/bad.pdf"],
                        timeout=10)
        launch_app(env, "document viewer")  # evince; will try /tmp/gui_seed pdf
        time.sleep(2)
        # force-open the bad file so the "Unable to open document" dialog shows
        _run_vm_command(env, ["bash", "-lc",
                              "DISPLAY=:0 evince /tmp/bad.pdf >/dev/null 2>&1 &"],
                        timeout=10)
        time.sleep(5)
        save(env, "evince__normal__none__errordialog.png")
    except Exception as e:
        print(f"[err] evince error dialog: {e}")

    print("[done] frames in", OUT)
    try:
        env.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
