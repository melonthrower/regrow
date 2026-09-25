#!/usr/bin/env bash
# 给种子 AVD 灌「带 ID3 标签的真音乐」→ 让 Retro Music 的 Albums/Artists 非空。
# 仿 android_world user_data_generation: 每首歌带 title+artist+album, 多专辑多艺术家,
# 推 /sdcard/Music 后做媒体扫描(等价 retro_music._scan_music_directory)。
#
# 前置: 已有「可写」(无 -read-only) Small_Phone_seeded 实例在 <console_port>。
# 用法: ./ops/seed_music.sh [console_port=5600]
# 之后须存快照: adb -s emulator-<port> emu avd snapshot save default_boot
set -u
PORT="${1:-5600}"
A=$HOME/android-sdk/platform-tools/adb
S=(-s "emulator-$PORT")
TMP=/tmp/seed_music; rm -rf "$TMP"; mkdir -p "$TMP"

gen() {  # freq  title  artist  album  track
  ffmpeg -loglevel error -f lavfi -i "sine=frequency=$1:duration=4" \
    -metadata title="$2" -metadata artist="$3" -metadata album="$4" \
    -metadata track="$5" -metadata genre="Demo" -id3v2_version 3 -y "$TMP/$2.mp3"
}
#    freq  title             artist          album            track
gen 261 "Midnight Drive"  "The Wanderers" "Night Roads"    1
gen 293 "City Lights"     "The Wanderers" "Night Roads"    2
gen 329 "Open Road"       "The Wanderers" "Night Roads"    3
gen 349 "Coastal Dreams"  "Luna Ray"      "Ocean Calm"     1
gen 392 "Slow Tide"       "Luna Ray"      "Ocean Calm"     2
gen 440 "Morning Light"   "Luna Ray"      "Ocean Calm"     3
gen 493 "Neon Avenue"     "Neon Pulse"    "Electric City"  1
gen 523 "Synth Horizon"   "Neon Pulse"    "Electric City"  2
gen 587 "Digital Heart"   "Neon Pulse"    "Electric City"  3
gen 659 "Acoustic Soul"   "Maya Stone"    "Unplugged"      1
gen 698 "Quiet Morning"   "Maya Stone"    "Unplugged"      2
gen 784 "Paper Boats"     "Maya Stone"    "Unplugged"      3
echo "[gen] $(ls "$TMP"/*.mp3 2>/dev/null | wc -l) 首带标签 mp3"

echo "[push] 清旧桩文件 + 推真音乐到 /sdcard/Music"
"$A" "${S[@]}" shell 'rm -f /sdcard/Music/*.mp3' 2>/dev/null
"$A" "${S[@]}" push "$TMP"/. /sdcard/Music/

echo "[scan] 媒体扫描"
"$A" "${S[@]}" shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Music >/dev/null 2>&1
"$A" "${S[@]}" shell 'for f in /sdcard/Music/*.mp3; do am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://$f"; done' >/dev/null 2>&1
sleep 6

echo "=== MediaStore 专辑 ==="
"$A" "${S[@]}" shell content query --uri content://media/external/audio/albums --projection album,artist 2>/dev/null | head
echo "=== MediaStore 艺术家 ==="
"$A" "${S[@]}" shell content query --uri content://media/external/audio/artists --projection artist 2>/dev/null | head
echo "[done] 验证完记得存快照: adb -s emulator-$PORT emu avd snapshot save default_boot"
