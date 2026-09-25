# Copyright 2024 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# References:
# - android_world/android_world/env/json_action.py action
# - android_world/android_world/env/adb_utils.py
# - android_world/android_world/env/setup_device/setup.py name
# - action type: android_world/android_world/env/actuation.py
# {
#     "task_id": "0",
#     "app_name": "com.taobao.taobao"
# },
# {
#     "task_id": "0",
#     "app_name": "com.ss.android.ugc.aweme"
# },

"""
配置文件，包含环境设置、命令行参数定义等。
"""

import os
from typing import Dict, List


# 屏幕截图保存目录
SCREEN_GPT_DIR = "./screenshots_gpt_v2"
# 指令文件路径
INSTRUCTION_PATH = "./os_genesis/example.json"

OS_TYPE = "ubuntu"
ACTION_TYPES = ["CLICK", "TYPE", "SCROLL"]  # 可用的动作类型
CLICK_ACTION_TYPES = ["CLICK", "LEFT_DOUBLE", "RIGHT_SINGLE", "DRAG"]
TYPE_ACTION_TYPES = ["TYPE", "FINISHED"]
HOTKEY_ACTION_TYPES = ["HOTKEY"]
SCROLL_ACTION_TYPES = ["SCROLL"]
ACTION_WEIGHTS = [1.0, 0.0, 0.0]       # 对应的权重
RANDOM_ACTION_DELAY = 2.0                       # 随机动作执行后的延迟时间（秒）
RANDOM_SCREENSHOTS_DIR = './screenshots_random' # 随机动作截图保存目录
DEFAULT_MIN_RANDOM_ACTIONS = 1                 # 默认随机动作最小值
DEFAULT_MAX_RANDOM_ACTIONS = 20          # 默认随机动作最大值
DEFAULT_MAX_GUIDED_ACTIONS = 0          # 默认引导动作最大值
DEFAULT_RANDOM_WALK_CROSS_APP = 1              # 默认随机游走跨app数
DEFAULT_MAX_GUIDED_ACTIONS_AFTER_OPENAPP=5          # 默认引导动作最大值（打开app后）
EVALUATE_TRAJECTORY = False

# ── Graph exploration constants (Design Decisions D1, D5, D9) ────────────
DEFAULT_MAX_GRAPH_STATES = 50
DEFAULT_MAX_GRAPH_ACTIONS = 200

# D1: Tags whose text contributes to the skeleton hash (anchor nodes)
ANCHOR_TAGS = {"frame", "heading", "tabelement"}

# D5: Mapping from EXC_INIT_APP names to launch commands for action replay
APP_BINARY_MAP: Dict[str, str] = {
    # Deterministic, repository-owned visual traversal fixture.  app_lifecycle
    # installs the generated standalone HTML into the guest before launch.
    "dayline": (
        "google-chrome --app=file:///tmp/gui_rewalk_fixture/index.html "
        "--user-data-dir=/tmp/gui_rewalk_fixture/profile --no-first-run "
        "--disable-default-apps --disable-features=Translate --class=dayline"
    ),
    "rewalk fixture": (
        "google-chrome --app=file:///tmp/gui_rewalk_fixture/index.html "
        "--user-data-dir=/tmp/gui_rewalk_fixture/profile --no-first-run "
        "--disable-default-apps --disable-features=Translate --class=dayline"
    ),
    "Chrome": "google-chrome",
    "LibreOffice writer": "libreoffice --writer --norestore",
    "LibreOffice calc": "libreoffice --calc --norestore",
    "GNU image": "gimp",
    "setting": "gnome-control-center",
    "calendar": "gnome-calendar",
    "calculator": "gnome-calculator",
    "Ubuntu Software": "gnome-software",
    "terminal": "gnome-terminal",
    "mines": "gnome-mines",
    # ── Batch 1: GNOME utilities ──
    "text editor": "gnome-text-editor",
    "system monitor": "gnome-system-monitor",
    "tweaks": "gnome-tweaks",
    "clocks": "gnome-clocks",
    "characters": "gnome-characters",
    "font viewer": "gnome-font-viewer",
    "disk usage": "baobab",
    "document viewer": "evince",
    "image viewer": "eog",
    "logs": "gnome-logs",
    # ── Batch 2: common desktop apps ──
    "firefox": "firefox",
    "thunderbird": "thunderbird",
    "vlc": "vlc",
    "shotwell": "shotwell",
    "rhythmbox": "rhythmbox",
    "inkscape": "inkscape",
    "transmission": "transmission-gtk",
    "cheese": "cheese",
    "scanner": "simple-scan",
    "files": "nautilus",
    "vs_code": "code",
    # ── Batch 3: 探测VM实装新增(2026-06-19, 无需登录的GTK应用) ──
    "disks": "gnome-disks",
    "seahorse": "seahorse",
    "todo": "gnome-todo",
    "gedit": "gedit",
    "archive": "file-roller",
    "sudoku": "gnome-sudoku",
    "mahjongg": "gnome-mahjongg",
    "solitaire": "sol",
    "videos": "totem",
    "backups": "deja-dup",
    "power statistics": "gnome-power-statistics",
    "network config": "nm-connection-editor",
    "libreoffice draw": "libreoffice --draw --norestore",
    "libreoffice impress": "libreoffice --impress --norestore",
}

# Apps that open into an empty "no content loaded" state. Seeding a sample file
# at launch makes the real
# UI — toolbars, page/zoom controls, menus, content actions — appear, so the
# traversal has something to explore instead of dead-ending at the root node.
# Maps app_name -> (vm_file_path, kind). kind ∈ {"txt", "png", "pdf"} drives
# in-VM sample-file generation (see _ensure_seed_file in traversal.py).
APP_SEED_FILE: Dict[str, tuple] = {
    "document viewer": ("/tmp/gui_seed/sample.pdf", "pdf"),
    "image viewer": ("/tmp/gui_seed/sample.png", "png"),
    "text editor": ("/tmp/gui_seed/sample.txt", "txt"),
    "gedit": ("/tmp/gui_seed/sample.txt", "txt"),
    # ── OSWorld 对齐: 指向 System_seeded.qcow2 已烤进的内容文件, 让应用启动即开进
    #    内容(_ensure_seed_file 见文件已存在→不重建→launch_app 带文件打开)。
    #    在非种子 VM 上文件不存在→优雅回退到空开(launch_app 仍可启动)。
    #    路径假定 System_seeded 烤入布局(/home/user/...); 已实测 Documents/budget.xlsx
    #    + Chrome 书签存在。用无空格路径避免 shlex 拆参。
    "LibreOffice calc": ("/home/user/Documents/budget.xlsx", "xlsx"),
    "LibreOffice writer": ("/home/user/Documents/project_plan.md", "txt"),
    "GNU image": ("/home/user/Pictures/vacation_beach.jpg", "jpg"),
    "vs_code": ("/home/user/Projects/todo-app", "dir"),
    # Impress/VLC 内容(soffice 由 flat-ODF 生成的 3 页 pptx / ffmpeg 生成的测试
    # 视频),已烤进 System_seeded.qcow2。Thunderbird 不在此表——它靠烤入的
    # ~/.thunderbird profile(账号 anonym-x2024@outlook.com 已配)直接 launch。
    "libreoffice impress": ("/home/user/Documents/quarterly_review.pptx", "pptx"),
    "vlc": ("/home/user/Videos/sample_clip.mp4", "mp4"),
}

# Known desktop process/window-title aliases used by wmctrl.
APP_WINDOW_NAME_MAP: Dict[str, List[str]] = {
    "dayline": [
        "Dayline",
        "dayline",
    ],
    "rewalk fixture": [
        "Dayline",
        "ReWalk Fixture App",
        "ReWalk Fixture",
        "rewalk-fixture",
    ],
    "setting": ["gnome-control-center", "Settings"],
    "Chrome": ["google-chrome", "Google Chrome", "Chrome"],
    "terminal": ["gnome-terminal", "Terminal"],
    "calculator": ["gnome-calculator", "Calculator"],
    "Ubuntu Software": [
        "gnome-software",
        "Ubuntu Software",
        "Software",
        "org.gnome.Software",
    ],
    "calendar": ["gnome-calendar", "Calendar"],
    "mines": ["gnome-mines", "Mines"],
    "LibreOffice calc": ["soffice", "libreoffice", "LibreOffice Calc", "LibreOffice"],
    "LibreOffice writer": ["soffice", "libreoffice", "LibreOffice Writer", "LibreOffice"],
    "GNU image": ["gimp", "GNU Image", "GIMP"],
    # ── Batch 1: GNOME utilities ──
    "text editor": ["gnome-text-editor", "Text Editor"],
    "system monitor": ["gnome-system-monitor", "System Monitor"],
    "tweaks": ["gnome-tweaks", "Tweaks"],
    "clocks": ["gnome-clocks", "Clocks"],
    "characters": ["gnome-characters", "Characters"],
    "font viewer": ["gnome-font-viewer", "Font Viewer", "Fonts"],
    "disk usage": ["baobab", "Disk Usage Analyzer", "Baobab"],
    "document viewer": ["evince", "Document Viewer", "Evince"],
    "image viewer": ["eog", "Image Viewer", "Eye of GNOME"],
    "logs": ["gnome-logs", "Logs"],
    # ── Batch 2: common desktop apps ──
    "firefox": ["firefox", "Firefox", "Mozilla Firefox"],
    "thunderbird": ["thunderbird", "Thunderbird", "Mozilla Thunderbird"],
    "vlc": ["vlc", "VLC", "VLC media player"],
    "shotwell": ["shotwell", "Shotwell", "Shotwell Photo Manager"],
    "rhythmbox": ["rhythmbox", "Rhythmbox"],
    "inkscape": ["inkscape", "Inkscape"],
    "transmission": ["transmission-gtk", "Transmission"],
    "cheese": ["cheese", "Cheese"],
    "scanner": ["simple-scan", "Simple Scan", "Document Scanner"],
    "files": ["nautilus", "org.gnome.Nautilus", "Files", "Nautilus"],
    "vs_code": ["code", "Code", "Visual Studio Code", "Vscode"],
}

# D11: Per-app commands to clear cached UI state before relaunch.
# Solves the "Settings remembers last sub-page" problem.
APP_CACHE_CLEAR_CMDS: Dict[str, List[str]] = {
    "dayline": [
        "rm -rf /tmp/gui_rewalk_fixture/profile",
    ],
    "rewalk fixture": [
        "rm -rf /tmp/gui_rewalk_fixture/profile",
    ],
    "setting": [
        "dconf reset -f /org/gnome/control-center/",
    ],
    "files": [
        "dconf reset -f /org/gnome/nautilus/",
    ],
    "calendar": [
        "dconf reset -f /org/gnome/calendar/",
    ],
    "LibreOffice calc": [
        "rm -rf ~/.config/libreoffice/4/user/backup/*",
        "rm -f ~/.config/libreoffice/4/.lock",
        "find /tmp -maxdepth 1 -name 'lu*' -delete 2>/dev/null",
        "sed -i '/Recovery\\/RecoveryList/d' ~/.config/libreoffice/4/user/registrymodifications.xcu 2>/dev/null",
    ],
    "LibreOffice writer": [
        "rm -rf ~/.config/libreoffice/4/user/backup/*",
        "rm -f ~/.config/libreoffice/4/.lock",
        "find /tmp -maxdepth 1 -name 'lu*' -delete 2>/dev/null",
        "sed -i '/Recovery\\/RecoveryList/d' ~/.config/libreoffice/4/user/registrymodifications.xcu 2>/dev/null",
    ],
    "firefox": [
        "rm -rf ~/.mozilla/firefox/*.default-release/sessionstore*",
    ],
    "thunderbird": [
        "rm -rf ~/.thunderbird/*.default-release/session.json",
    ],
    "shotwell": [
        "dconf reset -f /org/gnome/shotwell/",
    ],
    "inkscape": [
        "rm -rf ~/.config/inkscape/preferences.xml",
    ],
    "document viewer": [
        "dconf reset -f /org/gnome/evince/",
    ],
    "clocks": [
        "dconf reset -f /org/gnome/clocks/",
    ],
}

# D9: Static fallback dictionary for text-input fields
INPUT_DEFAULTS: Dict[str, str] = {
    "search": "test",
    "username": "user1",
    "password": "pass123",
    "email": "test@test.com",
    "url": "https://example.com",
    "filename": "test.txt",
    "default": "hello world",
}

EXC_INIT_APP = [
    "Chrome",
    "LibreOffice writer",
    "LibreOffice calc",
    "GNU image",
    "setting",
    "calendar",
    "calculator",
    "terminal",
    "mines",
    # ── Batch 1: GNOME utilities ──
    "text editor",
    "system monitor",
    "tweaks",
    "clocks",
    "characters",
    "font viewer",
    "disk usage",
    "document viewer",
    "image viewer",
    "logs",
    # ── Batch 2: common desktop apps ──
    "firefox",
    "thunderbird",
    "vlc",
    "shotwell",
    "rhythmbox",
    "inkscape",
    "transmission",
    "cheese",
    "scanner",
]

LOGIN_WEBSITE = [
    "www.baidu.com",
    "www.bing.com",
    "www.microsoft.com",
    "www.csdn.net",
    "www.anyknew.com",
    "github.com",
    "www.google.com",
    ""
]

TOTAL_ACTION_TYPES = [
    "CLICK", 
    "LEFT_DOUBLE", 
    "RIGHT_SINGLE", 
    "TYPE"
]

UBUNTU_APP_NAMES = [
    "Chrome", 
    "Thuderbird mail", 
    "Vscode", 
    "VLC media player", 
    "LibreOffice writer", 
    "LibreOffice calc", 
    "LibreOffice impress", 
    "GNU image", 
    "File", 
    "Ubuntu Software", 
    "Help", 
    "Trash",
    "Other"
]


def setup_environment():
    """设置环境变量"""
    ####### The complete version of the list of examples #######
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["GRPC_VERBOSITY"] = "ERROR"  # 只显示错误
    os.environ["GRPC_TRACE"] = "none"  # 禁用追踪


# ══════════════════════════════════════════════════════════════════════════
# Android (mobile) platform configuration
# ══════════════════════════════════════════════════════════════════════════

# app_name → (package, launch activity).  Activity 为空时用 monkey 拉起默认
# LAUNCHER activity。
APP_PACKAGE_MAP: Dict[str, tuple] = {
    # Repository-owned deterministic communication fixture. mobile_ops installs
    # the generated debug APK into the active AVD before first launch.
    "mingle": ("com.guirewalk.mingle", ".MainActivity"),
    # ── AOSP / Google built-ins (烟囱测试用) ──
    "android_settings": ("com.android.settings", ".Settings"),
    "android_clock": ("com.google.android.deskclock", ""),
    "android_calculator": ("com.google.android.calculator", ""),
    "android_files": ("com.google.android.documentsui", ""),
    "android_contacts": ("com.google.android.contacts", ""),
    "android_chrome": ("com.android.chrome", ""),
    # ── 新增 AOSP/Google 内置(无需登录, 有丰富UI, 2026-06-19扩展) ──
    "android_calendar": ("com.google.android.calendar", ""),
    "android_camera": ("com.android.camera2", ""),
    "android_photos": ("com.google.android.apps.photos", ""),
    "android_dialer": ("com.google.android.dialer", ""),
    "android_messaging": ("com.google.android.apps.messaging", ""),
    "android_maps": ("com.google.android.apps.maps", ""),
    # ── android_world 第三方 App(本地离线, 无需登录, 2026-06-30 对齐补全) ──
    "markor": ("net.gsantner.markor", ""),
    "joplin": ("net.cozic.joplin", ""),
    "tasks": ("org.tasks", ""),
    "simple_calendar_pro": ("com.simplemobiletools.calendar.pro", ""),
    "simple_sms_messenger": ("com.simplemobiletools.smsmessenger", ""),
    "simple_gallery_pro": ("com.simplemobiletools.gallery.pro", ""),
    "simple_draw_pro": ("com.simplemobiletools.draw.pro", ""),
    "retro_music": ("code.name.monkey.retromusic", ""),
    "vlc": ("org.videolan.vlc", ""),
    "audio_recorder": ("com.dimowner.audiorecorder", ""),
    "pro_expense": ("com.arduia.expense", ""),
    "broccoli": ("com.flauschcode.broccoli", ""),
    "opentracks": ("de.dennisguse.opentracks", ""),
    "osmand": ("net.osmand", ""),
    "clipper": ("ca.zgrs.clipper", ""),
    "miniwob": ("com.google.androidenv.miniwob", ""),
    # ── 国内主流 App ──
    "taobao": ("com.taobao.taobao", ""),
    "douyin": ("com.ss.android.ugc.aweme", ""),
    "wechat": ("com.tencent.mm", ""),
    "jd": ("com.jingdong.app.mall", ""),
    "meituan": ("com.sankuai.meituan", ""),
    "bilibili": ("tv.danmaku.bili", ""),
    "xiaohongshu": ("com.xingin.xhs", ""),
    "amap": ("com.autonavi.minimap", ""),
    "alipay": ("com.eg.android.AlipayGphone", ""),
}

# 回溯时允许 `pm clear`（清数据）的应用白名单。
# 国内 App（淘宝/微信等）清数据会丢登录态，绝不能加入这里；
# 它们的 hard-reset 只做 am force-stop + 重启。
ANDROID_CLEAR_DATA_APPS = {
    "mingle",
    "android_settings",
    "android_clock",
    "android_calculator",
    "android_files",
    "android_contacts",
}

# 视觉状态哈希的裁剪（像素）：顶部状态栏含时钟/电量等动态内容，
# 底部为手势导航条。
ANDROID_STATUS_BAR_CROP_PX = 80
ANDROID_NAV_BAR_CROP_PX = 48

# 默认 AVD 配置
ANDROID_DEFAULT_AVD = "Small_Phone"
ANDROID_DEFAULT_CONSOLE_PORT = 5554
ANDROID_DEFAULT_GRPC_PORT = 8554


def _normalize_app_key(name: str) -> str:
    """Canonicalise an app name: lowercase, treat space/-/_ as one separator.

    Lets a launcher pass display-style names ('Simple Gallery Pro',
    'simple gallery pro') and still hit the canonical map key
    ('simple_gallery_pro'). Without this the visual-traversal batch silently
    failed every third-party app with 'not in APP_PACKAGE_MAP'.
    """
    parts = (name or "").strip().lower().replace("-", " ").replace("_", " ").split()
    return "_".join(parts)


def _resolve_app_entry(app_name: str):
    """APP_PACKAGE_MAP lookup tolerant of separator/case differences."""
    if not app_name:
        return None
    entry = APP_PACKAGE_MAP.get(app_name)
    if entry:
        return entry
    target = _normalize_app_key(app_name)
    for key, val in APP_PACKAGE_MAP.items():
        if _normalize_app_key(key) == target:
            return val
    return None


def get_android_package(app_name: str) -> str:
    """Return the Android package for *app_name* ('' if unknown)."""
    entry = _resolve_app_entry(app_name)
    return entry[0] if entry else ""


def get_android_activity(app_name: str) -> str:
    """Return the launch activity for *app_name* ('' → default launcher)."""
    entry = _resolve_app_entry(app_name)
    return entry[1] if entry else ""


