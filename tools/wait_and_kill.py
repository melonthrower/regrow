import argparse
import json
import sys
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _post_execute(controller, command, timeout=20):
    payload = json.dumps({"command": command, "shell": False})
    response = requests.post(
        controller.http_server + "/execute",
        headers={"Content-Type": "application/json"},
        data=payload,
        timeout=timeout,
    )
    ok = response.status_code == 200
    text = response.text.strip() if response.text else ""
    return ok, text


def _get_process_name(app_name: str, app_binary_map) -> str:
    binary = app_binary_map.get(app_name, app_name.lower())
    return binary.split()[0].split("/")[-1]


def _kill_app(controller, app_name: str, app_binary_map, force: bool = False):
    process_name = _get_process_name(app_name, app_binary_map)
    if force:
        cmd = ["bash", "-lc", f"pkill -9 -f '{process_name}' || true"]
    else:
        cmd = ["pkill", "-f", process_name]
    ok, text = _post_execute(controller, cmd)
    print(f"[kill] process={process_name}, ok={ok}")
    if text:
        print(text)


def _clear_cache(controller, app_name: str, app_cache_clear_cmds):
    cmds = app_cache_clear_cmds.get(app_name, [])
    if not cmds:
        print(f"[cache] no clear commands configured for app={app_name}")
        return

    for cmd in cmds:
        ok, text = _post_execute(controller, ["bash", "-c", cmd])
        print(f"[cache] cmd={cmd}, ok={ok}")
        if text:
            print(text)


def _launch_app(controller, app_name: str, app_binary_map):
    binary = app_binary_map.get(app_name, app_name.lower())
    cmd = f"nohup {binary} &>/dev/null &"
    ok, text = _post_execute(controller, ["bash", "-c", cmd])
    print(f"[launch] app={app_name}, binary={binary}, ok={ok}")
    if text:
        print(text)


def _check_process(controller, app_name: str, app_binary_map):
    process_name = _get_process_name(app_name, app_binary_map)
    ok, text = _post_execute(controller, ["bash", "-lc", f"pgrep -af '{process_name}' || true"])
    print(f"[check] process={process_name}, ok={ok}")
    if text:
        print(text)


def reset_app(
    controller,
    app_name: str,
    app_binary_map,
    app_cache_clear_cmds,
    force_kill: bool,
    settle_s: float,
):
    print(f"\n[reset] start for app={app_name}")
    _kill_app(
        controller,
        app_name=app_name,
        app_binary_map=app_binary_map,
        force=force_kill,
    )
    time.sleep(settle_s)
    _clear_cache(
        controller,
        app_name=app_name,
        app_cache_clear_cmds=app_cache_clear_cmds,
    )
    _launch_app(controller, app_name=app_name, app_binary_map=app_binary_map)
    time.sleep(settle_s)
    _check_process(controller, app_name=app_name, app_binary_map=app_binary_map)
    print("[reset] done")


def main():
    parser = argparse.ArgumentParser(
        description="Start VM, wait for your input to reset app repeatedly, then close VM."
    )
    parser.add_argument("--path_to_vm", default=r"C:\Users\Admin\Desktop\GUI agent\GUI-ReWalk\OSWorld\vmware_vm_data\Ubuntu0\Ubuntu0.vmx", help="Path to .vmx file")
    parser.add_argument("--vm_provider", default="vmware", choices=["vmware"], help="VM provider")
    parser.add_argument("--app_name", default="setting", help="Target app key in APP_BINARY_MAP")
    parser.add_argument("--snapshot_name", default="init_state", help="Snapshot name")
    parser.add_argument("--headless", action="store_true", help="Run VM in headless mode")
    parser.add_argument("--force_kill", action="store_true", help="Use pkill -9 -f")
    parser.add_argument("--settle_s", type=float, default=1.5, help="Wait seconds between reset steps")
    parser.add_argument("--end_cmd", default="exit", help="Type this command to end loop and close VM")
    parser.add_argument("--max_cycles", type=int, default=0, help="0 means unlimited")
    args = parser.parse_args()

    vm_path = Path(args.path_to_vm).expanduser()
    if not vm_path.is_absolute():
        vm_path = (Path.cwd() / vm_path).resolve()

    if not vm_path.exists():
        print(f"[error] VM path not found: {vm_path}")
        print("[hint] If running from tools/, use ../OSWorld/... or an absolute path.")
        sys.exit(2)

    from gui_rewalk.env.desktop_gui_gen_env import DesktopGUIGenEnv
    from gui_rewalk.src.config.config import APP_BINARY_MAP, APP_CACHE_CLEAR_CMDS

    env = None
    cycle = 0
    try:
        print("[vm] starting virtual machine...")
        env = DesktopGUIGenEnv(
            provider_name=args.vm_provider,
            path_to_vm=str(vm_path),
            snapshot_name=args.snapshot_name,
            action_space="gen_data",
            headless=args.headless,
            os_type="Ubuntu",
        )

        print(f"[vm] started. controller={env.controller.http_server}")
        print(f"[loop] app={args.app_name}. Press Enter to reset after your manual operation.")
        print(f"[loop] type '{args.end_cmd}' to finish and close VM.")

        _launch_app(env.controller, args.app_name, APP_BINARY_MAP)
        time.sleep(args.settle_s)
        _check_process(env.controller, args.app_name, APP_BINARY_MAP)

        while True:
            if args.max_cycles > 0 and cycle >= args.max_cycles:
                print(f"[loop] reached max_cycles={args.max_cycles}")
                break

            user_input = input(
                f"\n[cycle {cycle + 1}] finish your operation, press Enter to reset (or '{args.end_cmd}' to stop): "
            ).strip()

            if user_input.lower() == args.end_cmd.lower():
                print("[loop] received end command")
                break

            cycle += 1
            reset_app(
                controller=env.controller,
                app_name=args.app_name,
                app_binary_map=APP_BINARY_MAP,
                app_cache_clear_cmds=APP_CACHE_CLEAR_CMDS,
                force_kill=args.force_kill,
                settle_s=args.settle_s,
            )

        print(f"[summary] completed reset cycles: {cycle}")

    finally:
        if env is not None:
            print("[vm] closing virtual machine...")
            env.close()
            print("[vm] closed")


if __name__ == "__main__":
    main()
