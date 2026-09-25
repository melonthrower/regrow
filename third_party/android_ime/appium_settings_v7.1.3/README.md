# Appium Settings headless IME

Pinned upstream artifact used only inside owned Android named-snapshot overlays.

- Source: https://github.com/appium/io.appium.settings
- Release: `v7.1.3`
- Asset: `settings_apk-debug.apk`
- Local file: `io.appium.settings-v7.1.3.apk`
- SHA-256: `16af5bb042573f300755ce09c84811ef9f2ffc585a3ed0b930a44c599df2fa32`
- Package: `io.appium.settings`
- Input method: `io.appium.settings/.UnicodeIME`
- License: Apache-2.0; see `LICENSE` and `NOTICE.txt`.

The environment verifies the digest before installation. The APK is installed
into the run-local read-only emulator overlay, selected as the current IME, and
discarded with that overlay. It is not a target application, seed object, GUI
Region, traversal action, or acceptance evidence.
