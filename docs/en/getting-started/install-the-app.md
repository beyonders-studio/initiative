---
icon: lucide/smartphone
---

# Install the app

Initiative runs in a browser, and using it that way forever is a respectable life choice. You can also give it its own icon and window, and on Android, notifications that arrive while the app is closed. None of these takes longer than finding the charger.

## Find the right version for your device

Your server has a **Download** page that works out what you're on and offers the right thing. Open your Initiative address with `/download` on the end, such as `https://initiative.example.com/download`. The **Get the app** step in Home's **Getting started** list goes there too.

| You're on | Get |
|---|---|
| An Android phone or tablet | [The Android app](#install-the-android-app) |
| An iPhone or iPad | [Initiative on your Home Screen](#on-an-iphone-or-ipad), from Safari |
| A Windows, Mac or Linux computer | [The desktop app](#the-desktop-app), or [the browser version](#on-a-computer) |
| Anything else with a screen | Nothing to install. Bookmark the address. |

Every version is the same Initiative with the same account, so you can mix them freely.

## Install it from the browser

Your browser can install Initiative as an app of its own: an icon on your home screen or dock, a window without the browser around it, and you stay signed in. Browsers only offer this on a secure `https://` address. If yours starts with `http://`, the option won't appear, and that's a question for whoever set up the server.

### On an iPhone or iPad

1. Open your Initiative address in Safari.
2. Tap the Share button.
3. Tap **Add to Home Screen**.
4. Tap **Add**.

On an iPhone or iPad, notifications collect in the bell inside the app rather than arriving as push notifications.

### On an Android phone

1. Open your Initiative address in Chrome.
2. Tap the ⋮ menu.
3. Tap **Install app** or **Add to Home screen**.

The [Android app](#install-the-android-app) does more, including push notifications and reading offline, so it's usually the better pick.

### On a computer

- **Chrome or Edge:** select the install icon at the right-hand end of the address bar, or **Or install it from the browser** on the Download page.
- **Safari on a Mac:** choose **File**, then **Add to Dock**.

Other browsers keep Initiative in a tab, which works just as well and looks less like an app.

## Install the Android app

The Android app installs without an app store, and runs on Android 7.0 or later.

1. On your phone, open your server's Download page.
2. Tap **Download for Android**.
3. Open the downloaded file.
4. When Android asks whether to allow apps from this source, allow it for your browser.
5. Tap **Install**.

Android checks because the app didn't come from an app store, and you did mean it.

To have the app updated for you whenever a new one comes out, [add Initiative to Obtainium](https://apps.obtainium.imranr.dev/redirect?r=obtainium%3A%2F%2Fadd%2Fhttps%3A%2F%2Fgithub.com%2Fbeyonders-studio%2Finitiative), a free app that installs new versions from a project's releases. Installing by hand from the [releases page](https://github.com/beyonders-studio/initiative/releases)? Take the newest release with an `.apk` attached. That often isn't the top one, because the app is only rebuilt when it changes.

## Install the desktop app { #the-desktop-app }

There's an app for Windows, Mac and Linux. It opens in its own window, signs in as one of your devices, and shows notifications when Initiative isn't the window in front.

1. On your computer, open your server's Download page.
2. Select **Download for Windows**, **Download for Mac** or **Download for Linux**.
3. Open the file you downloaded and install it the way you'd install anything else.

You get an `.exe` installer for Windows, a `.dmg` for a Mac and a `.deb` for Debian and Ubuntu. The same files are on the [releases page](https://github.com/beyonders-studio/initiative/releases).

!!! note "Your computer will ask whether you meant it"
    The installers aren't signed with a publisher's certificate, so Windows and macOS stop to check. On Windows, choose **More info**, then **Run anyway**. On a Mac, open the app once, then go to **System Settings › Privacy & Security** and choose **Open Anyway**.

## Connect the app to your server

The Android and desktop apps ask which Initiative to talk to the first time you open them.

1. Open the app.
2. Leave **Self-hosted** chosen under **Server**.
3. Type your group's Initiative address, the same one you use in a browser, such as `https://initiative.example.com`.
4. Select **Connect**.
5. [Sign in](signing-in.md).

The app remembers the server and keeps you signed in. The Android app only connects to `https://` addresses; if you get "The app connects to HTTPS servers only", ask whoever runs your server.

## Switch the app to another server

1. On the sign-in card, select the server's name after **Sign in to**.
2. Select **Your own server**.
3. Type the new address and select **Connect**.

Switching signs you out of the old server. The app keeps the last address you typed, in case you want to go back. Signed in already? Go to **My Settings › Account**, select **Disconnect** under **Server connection**, and the app signs out and asks for a server again.

## Turn on push notifications on Android

The Android app can notify you while it's closed, once whoever runs your server has [switched push on](../running-a-server/push-notifications.md).

1. A few seconds after you sign in, a banner says **Enable Push Notifications**. Select **Enable**.
2. Allow notifications when Android asks.

Dismissed the banner? Go to **My Settings › Notifications** and select **Turn on** under **Push notifications**. If it says **Blocked**, open your phone's settings, find Initiative, and allow notifications there. Which things notify you is up to you; see [Notifications](../guides/notifications.md).

## Share something into Initiative from another app

On Android, Initiative turns up in the share sheet. Found the venue's address in a text, a photo of the broken coffee urn, or last year's minutes as a PDF? Share it.

1. In the other app, tap Share and pick **Initiative**.
2. Choose what it becomes: **Task**, **Document**, **File** or **Post**.
3. Pick where it goes, under **Select a community**, **Select an initiative** and, for a task, **Select a project**.
4. Check the **Title** and **Note**, or each file's name.
5. Select **Create task**, **Create document**, **Post** or **Upload file**.

Initiative opens what you made. The place you shared to last time sits at the top as **Last used**, so the next one is two taps. **File** appears when you share files, and uploads them as they are; a task, document or post keeps the pictures and leaves other files out. Not signed in? Sign in, and the share is waiting on the other side.

## Read offline in the app

The Android and desktop apps keep what you've opened recently on the device. When the train goes into a tunnel, a banner says you're offline and showing what this device last loaded, and you can keep reading projects, tasks, documents and the rest. Changing anything needs a connection again, and signing out clears what the device kept.

## Keep the app up to date

Initiative updates itself to match your server. When a new version is ready, a message says so; select **Reload** and you're on it. Busy? The **Update** button waits beside the bell until you are, or in the title bar of the desktop app.

Once in a while a release needs a newer app rather than a reload. Initiative says **App update required**:

- **On Android,** select **Download** and install the new app over the old one. Obtainium does this for you.
- **On Windows and Linux,** select **Update now**. Leave **Always update automatically** ticked and later updates download on their own, then ask you to **Restart**. Change your mind with **Update the app automatically** in **My Settings › Preferences**.
- **On a Mac,** select **Download** and install the new app.

## Keep the desktop app running in the background

On Windows and Linux, closing the window leaves Initiative in the tray so notifications keep arriving. Select the tray icon to bring the window back, or **Quit Initiative** in its menu to close it properly. A Mac keeps it in the dock, as Macs do.

Two switches in **My Settings › Preferences**, under **This device**, change this:

- **Keep running when the window closes** (Windows and Linux)
- **Open when the computer starts**

The app's icon shows how many notifications you haven't read. The question mark in the title bar opens Help.

## Set up Initiative on a new Android phone

Restore your old phone's backup onto the new one and the app comes back with your server address and settings. It asks you to sign in again, because your sign-in stays with the old phone. Your message history arrives once you verify the new phone from a device you already use; see [Messages](../guides/messages.md).

??? techspec "How the apps update over the air"
    Each server image carries the app bundle that matches its version, served from `/api/v1/native/bundle/`, with a statement of that bundle (version, SHA-256 checksum, and the oldest app it runs on) signed with the project's release key. On launch and whenever it comes to the foreground, the app reads the manifest, checks the signature against the keys it was built with, downloads the bundle, verifies its checksum and swaps it in behind the splash screen. A bundle without a valid signature is ignored, and the app stays on its version. A bundle older than the installed app is ignored too, and one that fails to start is rolled back.

    A bundle can only replace web assets, never native code. Each declares a minimum native version (`minNativeVersion`, and `minDesktopVersion` for the desktop app); an app older than that is asked to update itself. The release builds a new APK or desktop installer only when that floor moves, so most releases attach none. An updater watching the releases falls back to the last one that did, which is the build you want.

    A browser checks the server's version every 5 minutes and offers the same reload.
