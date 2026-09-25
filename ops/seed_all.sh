#!/usr/bin/env bash
# 综合播种「文件型」用户数据到可写 Small_Phone_seeded:音乐/照片/Markor笔记/文档。
# 媒体扫描后 *必须* 存快照,否则只读遍历实例看不到:
#   adb -s emulator-<port> emu avd snapshot save default_boot
#
# 覆盖: Retro Music(音乐) / Simple Gallery(照片) / Markor(笔记) / Files(文档)。
# 不覆盖: app 私有DB型(Tasks/Calendar 已有种子;Broccoli/ProExpense 需 UI 或
#         android_world task-init,另行处理)。
# 用法: ./ops/seed_all.sh [console_port=5600]
set -u
PORT="${1:-5600}"
A=$HOME/android-sdk/platform-tools/adb
S=(-s "emulator-$PORT")
sh() { "$A" "${S[@]}" shell "$@"; }
push() { "$A" "${S[@]}" push "$1" "$2" >/dev/null; }
T=/tmp/seed_all; rm -rf "$T"; mkdir -p "$T"/music "$T"/pics "$T"/notes "$T"/docs

echo "### 1) 音乐(带 ID3 标签) -> /sdcard/Music"
mg(){ ffmpeg -loglevel error -f lavfi -i "sine=frequency=$1:duration=4" \
  -metadata title="$2" -metadata artist="$3" -metadata album="$4" \
  -metadata track="$5" -metadata genre=Demo -id3v2_version 3 -y "$T/music/$2.mp3"; }
mg 261 "Midnight Drive" "The Wanderers" "Night Roads"   1
mg 293 "City Lights"    "The Wanderers" "Night Roads"   2
mg 329 "Open Road"      "The Wanderers" "Night Roads"   3
mg 349 "Coastal Dreams" "Luna Ray"      "Ocean Calm"    1
mg 392 "Slow Tide"      "Luna Ray"      "Ocean Calm"    2
mg 440 "Morning Light"  "Luna Ray"      "Ocean Calm"    3
mg 493 "Neon Avenue"    "Neon Pulse"    "Electric City" 1
mg 523 "Synth Horizon"  "Neon Pulse"    "Electric City" 2
mg 659 "Acoustic Soul"  "Maya Stone"    "Unplugged"     1
mg 698 "Quiet Morning"  "Maya Stone"    "Unplugged"     2
sh 'rm -f /sdcard/Music/*.mp3' 2>/dev/null; push "$T/music/." /sdcard/Music/

echo "### 2) 照片 -> /sdcard/Pictures + /sdcard/DCIM/Camera"
pic(){ ffmpeg -loglevel error -f lavfi -i "color=c=$1:s=$2" -frames:v 1 -y "$T/pics/$3.jpg"; }
pic RoyalBlue 1080x1920 sunset_beach;  pic ForestGreen 1200x900 forest_trail
pic OrangeRed 1600x1200 city_skyline;  pic SlateGray  900x1600 mountain_view
pic Teal      1080x1080 coffee_cup;    pic Purple     1920x1080 night_lights
sh 'mkdir -p /sdcard/DCIM/Camera' 2>/dev/null
push "$T/pics/." /sdcard/Pictures/; push "$T/pics/." /sdcard/DCIM/Camera/

echo "### 3) Markor 笔记 -> /storage/emulated/0/Documents/Markor"
printf '# Shopping List\n\n- [ ] Milk\n- [ ] Eggs\n- [x] Bread\n- [ ] Coffee\n' > "$T/notes/Shopping List.md"
printf '# Meeting Notes\n\n## 2026-06-30\n- Discuss Q3 roadmap\n- Assign owners\n- Next sync Friday\n' > "$T/notes/Meeting Notes.md"
printf '# Ideas\n\n1. Weekend hiking trip\n2. Learn guitar\n3. Read more books\n' > "$T/notes/Ideas.md"
printf '# Pancakes Recipe\n\n**Ingredients**: flour, eggs, milk, sugar\n\n**Steps**: mix, pour, flip.\n' > "$T/notes/Pancakes.md"
sh 'mkdir -p /storage/emulated/0/Documents/Markor' 2>/dev/null
push "$T/notes/." /storage/emulated/0/Documents/Markor/

echo "### 4) 文档 -> Documents + Download"
printf 'Quarterly report draft.\nRevenue up 12%%.\n' > "$T/docs/Report.txt"
printf 'todo: book flights, pay rent, call dentist\n' > "$T/docs/Todo.txt"
sh 'mkdir -p /sdcard/Download' 2>/dev/null
push "$T/docs/." /storage/emulated/0/Documents/; push "$T/docs/." /sdcard/Download/

echo "### 媒体扫描"
for d in Music Pictures DCIM Download Documents; do sh am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file:///sdcard/$d" >/dev/null 2>&1; done
sh 'for f in /sdcard/Music/*.mp3 /sdcard/Pictures/*.jpg /sdcard/DCIM/Camera/*.jpg; do am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://$f"; done' >/dev/null 2>&1
sleep 6

echo "=== 验证 ==="
echo -n "  音频: "; sh content query --uri content://media/external/audio/media --projection title 2>/dev/null | grep -c Row
echo -n "  专辑: "; sh content query --uri content://media/external/audio/albums --projection album 2>/dev/null | grep -c Row
echo -n "  图片: "; sh content query --uri content://media/external/images/media --projection _id 2>/dev/null | grep -c Row
echo -n "  Markor笔记: "; sh 'ls /storage/emulated/0/Documents/Markor/*.md 2>/dev/null | wc -l'
echo "[done] 验证 OK 后存快照: adb -s emulator-$PORT emu avd snapshot save default_boot"
