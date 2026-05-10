# K7 Android App

Android-first direct lamp controller. The app runs a local bridge inside the
phone and talks directly to the lamp at `192.168.4.1:8266` over WiFi.

Connect your phone to the lamp's WiFi before using Read, Preview, or Push.

**What the Android app can and can't do:**

- ✓ Edit and push schedules, read the lamp, save profiles and backups
- ✓ Feed mode and Maintenance mode — via the home screen widget (works without the app open)
- ✗ Smooth Ramp, Acclimation, Seasonal Shift — these always-on features require the ESP32 controller

## Home screen widget

The app includes a **K7 Feed & Maintenance** home screen widget. Long-press your home screen, choose Widgets, and add it. The widget works independently — the app does not need to be open.

- Tap **Feed** to start a 10-minute bright-white boost for feeding; tap again to cancel early
- Tap **Maintenance** to start a 30-minute balanced inspection light; tap again to cancel early
- A live countdown timer appears below the active button and ticks down automatically
- The active button changes colour so you can see the mode at a glance
- Starting one mode automatically cancels the other

## Sideloading (end users)

The app is not yet on the Play Store. To install manually:

1. On your Android phone go to **Settings → Apps → Special app access →
   Install unknown apps**. Tap your browser or file manager and enable
   **Allow from this source**.
2. Download `K7-Controller-v….apk` from the
   [releases page](https://github.com/bitbarista/k7-led-controller/releases).
3. Tap the downloaded file and tap **Install**.
4. Connect the phone to the lamp's WiFi (K7-XXXXXX) and open **K7 Controller**.
5. Tap **Read** to load the lamp's current settings.

Build the sideloadable debug APK:

```sh
JAVA_HOME=$PWD/.android-tools/jdk-17.0.19+10 \
ANDROID_HOME=$PWD/.android-sdk \
GRADLE_USER_HOME=$PWD/.android-tools/gradle-home \
.android-tools/gradle-8.7/bin/gradle :android-app:assembleDebug
```

APK output:

```text
android/app/build/outputs/apk/debug/K7-Controller-v0.1.0.apk
```
