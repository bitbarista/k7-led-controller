# K7 Android App

Android-first direct lamp controller. This target uses the shared web UI in a
WebView and serves a small localhost API bridge inside the app.

The phone must be connected to the lamp WiFi before using Read, Preview, or
Push. The app talks directly to the lamp at `192.168.4.1:8266`.

Build the sideloadable debug APK:

```sh
JAVA_HOME=$PWD/.android-tools/jdk-17.0.19+10 \
ANDROID_HOME=$PWD/.android-sdk \
GRADLE_USER_HOME=$PWD/.android-tools/gradle-home \
.android-tools/gradle-8.7/bin/gradle :android-app:assembleDebug
```

APK output:

```text
android/app/build/outputs/apk/debug/android-app-debug.apk
```
