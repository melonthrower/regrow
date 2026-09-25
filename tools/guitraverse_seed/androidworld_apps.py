"""Official AndroidWorld APK objects selected for the v2 builder."""

from __future__ import annotations

from dataclasses import dataclass


_GCS_PREFIX = "https://storage.googleapis.com/gresearch/android_world/"


@dataclass(frozen=True)
class AndroidWorldApkSource:
    adapter_id: str
    package: str
    filename: str
    expected_sha256: str = ""
    expected_size_bytes: int = 0

    @property
    def gcs_object(self) -> str:
        return f"{_GCS_PREFIX}{self.filename}"


ANDROIDWORLD_APPS = (
    AndroidWorldApkSource("markor", "net.gsantner.markor", "net.gsantner.markor_146.apk"),
    AndroidWorldApkSource("clipper", "ca.zgrs.clipper", "clipper.apk"),
    AndroidWorldApkSource("simple_calendar", "com.simplemobiletools.calendar.pro", "com.simplemobiletools.calendar.pro_238.apk"),
    AndroidWorldApkSource("tasks_org", "org.tasks", "org.tasks_130605.apk"),
    AndroidWorldApkSource("simple_draw", "com.simplemobiletools.draw.pro", "com.simplemobiletools.draw.pro_79.apk"),
    AndroidWorldApkSource("simple_gallery", "com.simplemobiletools.gallery.pro", "com.simplemobiletools.gallery.pro_396.apk"),
    AndroidWorldApkSource("simple_sms", "com.simplemobiletools.smsmessenger", "com.simplemobiletools.smsmessenger_85.apk"),
    AndroidWorldApkSource("audio_recorder", "com.dimowner.audiorecorder", "com.dimowner.audiorecorder_926.apk"),
    AndroidWorldApkSource("miniwob", "com.google.androidenv.miniwob", "miniwobapp.apk"),
    AndroidWorldApkSource("pro_expense", "com.arduia.expense", "com.arduia.expense_11.apk"),
    AndroidWorldApkSource("broccoli", "com.flauschcode.broccoli", "com.flauschcode.broccoli_1020600.apk"),
    AndroidWorldApkSource("osmand", "net.osmand", "net.osmand-4.6.13.apk"),
    AndroidWorldApkSource("open_tracks", "de.dennisguse.opentracks", "de.dennisguse.opentracks_5705.apk"),
    AndroidWorldApkSource("vlc", "org.videolan.vlc", "org.videolan.vlc_13050408.apk"),
    AndroidWorldApkSource("joplin", "net.cozic.joplin", "net.cozic.joplin_2097740.apk"),
    AndroidWorldApkSource("retro_music", "code.name.monkey.retromusic", "code.name.monkey.retromusic_10603.apk"),
)

# AndroidWorld also carries this VLC build. It is retained as the named
# alternate because the v2 builder live check selected the other candidate.
VLC_ALTERNATE_CANDIDATE = AndroidWorldApkSource(
    "vlc", "org.videolan.vlc", "org.videolan.vlc_13050407.apk")
