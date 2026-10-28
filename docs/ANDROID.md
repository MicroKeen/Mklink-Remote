# Android status

The product in this repository is currently qualified on Windows. An Android environment was prepared during development, but full mobile USB/BLE/network/debug flows are not qualified or shipped here.

The portable `android-env.ps1` and `android-doctor.ps1` helpers read `desktop/mklink-wireless-config/.android-env.local.json`, which must remain local. Supply your own JAVA_HOME, ANDROID_HOME and NDK_HOME. No developer's SDK paths, caches, signing keys or experimental Android output are published.

Do not interpret the environment check as support for every desktop feature on Android. An Android port requires platform-specific permissions, transport adapters, device tests and its own release qualification.
