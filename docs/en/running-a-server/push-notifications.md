---
icon: lucide/bell-ring
---

# Push notifications

Push is optional. In-app and email notifications work without it, so turn it on only if you want alerts to buzz in people's pockets as well, which they will, mostly about overdue tasks.

## Turn push on

Only an [owner](platform-roles.md) can do this.

1. Open **Settings → Platform → Push notifications**.
2. Switch on **Send push notifications**.
3. Select **Save push settings**.

Leave every other field empty. Your server then sends pushes through BeyondersStudio's push relay, which holds the app's credentials with Apple and Google so you don't need any. The app on people's phones picks the change up the next time it opens. There's nothing to restart, nothing to rebuild and no Firebase console involved.

Push also needs **Phone and desktop notifications** on, under **Settings → Platform → Security → Notifications that leave the app**. It starts on. That switch decides whether a notification may leave the app at all. Every community is held to it as a ceiling: one with **Its own security standard** can turn push off for itself, and none can turn it on while you have it off. Turning it off also deletes every device registration the server holds.

## Which way each phone is reached

| Phone | Goes through | What your server stores for it |
|---|---|---|
| iPhone | The relay, always. Apple only accepts pushes for the app signed with BeyondersStudio's key. | A relay handle |
| Android, no service account saved | The relay | A relay handle |
| Android, with your own service account | Your Firebase project, directly. The relay isn't involved. | The phone's own Firebase token |

Nothing contacts the relay until you switch push on.

### How the relay reaches a phone

Apple and Google address a phone by its device token. With the relay in the middle, your server never holds one.

1. **Your server registers with the relay** the first time a phone that needs the relay asks for the push settings, or the first time it sends a push through the relay, whichever comes first. It sends no name or address of its own (every server registers as "Initiative server"). It gets back an id and a key, and stores both in its database, the key encrypted with `SECRET_KEY`. The id is public and handed to the app. The key stays on your server.
2. **The phone trades its token for a handle.** The app sends its device token straight to the relay with your server's id, and gets back a handle (`rh_` and 43 more characters) that reaches this phone for your server only. The relay's address, `https://push-relay.beyonders.studio`, is built into the app, so no server can change where tokens go.
3. **Your server is told the handle**, never the token, and sends to it. The relay checks the handle belongs to your server and passes the message on to Apple or Google.

The app asks the relay for a fresh handle once a week, or sooner if the token, the server or the server's relay id changes. Signing out, or pointing the app at a different server, deletes the handle at the relay and at your server. If the relay answers that a handle is gone (the app was uninstalled, or Apple or Google retired the token), your server deletes it too.

A server with its own Firebase project and no iPhones never contacts the relay at all.

### What the relay sees

The relay learns which server a device belongs to and when that device gets a notification. Your server sends it the notification's title and text, the notification type and the in-app path it opens, the Android channel, and the badge count on an iPhone. BeyondersStudio states that the relay passes the title and text on to Apple or Google without storing or logging them.

A server that must not talk to anything outside your network can't use push through any public app, ours included. Android can go through your own Firebase project, below. An iPhone app would have to be built and signed under your own Apple account.

## Use your own Firebase project for Android

This is optional, for Android pushes to go straight through a Firebase project of your own. Everything goes on the same settings page, and the published app fetches what it needs from your server. You don't commit a `google-services.json` anywhere or rebuild the app.

Use a separate Firebase project for each deployment.

### Set up the Firebase project

1. Open the [Firebase console](https://console.firebase.google.com/).
2. Select **Add project**, or pick an existing one, and follow the prompts.
3. Add an **Android** app with the package name `studio.beyonders.initiative`, exactly.
4. Download the `google-services.json` it generates. You'll read four values out of it.
5. Go to **Project settings → Service accounts** and select **Generate new private key**.
6. Keep the key file somewhere safe. It's the one secret in all this, so it never goes into source control.

### Fill in the settings

1. Open **Settings → Platform → Push notifications**.
2. Switch on **Send push notifications**.
3. Fill in the four fields from the table below.
4. Open the key file from the Firebase steps and paste the whole thing into **Service account key**, braces and all.
5. Select **Save push settings**.

| Field | From `google-services.json` | Or in the Firebase console |
|---|---|---|
| **Project ID** | `project_info.project_id` | **Project settings → General → Project ID** |
| **App ID** | `client[0].client_info.mobilesdk_app_id` | **Project settings → General → Your apps → App ID** |
| **Web API key** | `client[0].api_key[0].current_key` | **Project settings → General → Web API key** |
| **Sender ID** | `project_info.project_number` | **Project settings → Cloud Messaging → Sender ID** |

The page refuses a key that isn't one complete JSON object, so a half-copied key is caught before it's stored. The key is encrypted with `SECRET_KEY` and never shown again. Once saved, the field says **A key is saved. Paste a new one to replace it.** Leave it blank when you edit the other fields and the saved key stays.

To rotate the key, generate a new one in Firebase, paste it over the old one, then delete the old key in Firebase. Give the service account only the Firebase Cloud Messaging permission it needs.

### Go back to the relay

The page has no button that removes a saved key. Send an empty one through the API instead, as an owner with a personal API key that isn't read-only:

```bash
curl -X PUT https://initiative.example.com/api/v1/settings/push \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "service_account_json": ""}'
```

This request replaces every push setting, so a field it leaves out is cleared. The four Firebase fields aren't needed on the relay.

Switching either way sorts itself out. The tokens your server holds stop matching how it now sends, so it deletes each one the first time it tries to use it, without sending anything. Each phone registers the right kind the next time the app opens.

??? techspec "Pre-filling from environment variables"
    On a fresh install's first boot, these variables fill in the settings page. After that the page owns them and the variables are ignored, so a change goes on the page, not in the environment.

    | Variable | Fills in | Default |
    |---|---|---|
    | `FCM_ENABLED` | **Send push notifications** | `false` |
    | `FCM_PROJECT_ID` | **Project ID** | Unset |
    | `FCM_APPLICATION_ID` | **App ID** | Unset |
    | `FCM_API_KEY` | **Web API key** | Unset |
    | `FCM_SENDER_ID` | **Sender ID** | Unset |
    | `FCM_SERVICE_ACCOUNT_JSON` | **Service account key**, stored encrypted | Unset |

## Check it works

1. Fetch what an iPhone would be told:

    ```bash
    curl "https://initiative.example.com/api/v1/settings/fcm-config?platform=ios"
    ```

    With push on, the answer has `"enabled": true` and a `push_relay_server_id`. Without a service account, `android_via_relay` is `true` and the Firebase fields are the relay's. Leave off `?platform=` and the relay id isn't included.

2. Open the app on a phone and turn on push in its settings. It should work without an error.
3. Assign yourself a task from another account and wait for the buzz.

The app reads these settings each time it opens, and the server rereads its own saved settings at most 30 seconds after a change.

## Your network

- Your server needs outbound HTTPS to `https://push-relay.beyonders.studio`, and phones need to reach it too. Nothing has to reach your server from the internet for push, because the relay never calls it.
- With your own Firebase project, your server also needs outbound HTTPS to `https://fcm.googleapis.com` and to Google's token endpoint.
- You don't need an account with BeyondersStudio for the relay.

## Troubleshooting

The messages in the first column appear in the server log.

| Symptom | What it means |
|---|---|
| `FCM not enabled, skipping push notification` | **Send push notifications** is off. Turn it on and save. |
| `push relay: could not register` | The server couldn't reach the relay. Check outbound HTTPS to `push-relay.beyonders.studio`. It tries again at most once every 300 seconds, on the next push or the next phone asking for settings. |
| `push relay: registration refused` | The relay turned down the registration. It accepts only a few registrations a day from one address, so wait and it retries on its own. |
| `Push relay credentials unavailable` | A push needed the relay and the server has no registration yet. See the two rows above. |
| `Push relay authentication failed (status 401, …)` | The relay stopped accepting this server's key. The server forgets it and registers again on the next push. Phones pick up the new id the next time the app opens. |
| `Push relay refused this server (status 403, …)` | The relay has suspended this server. Get in touch with BeyondersStudio. |
| `FCM project id not set, skipping push notification` | A service account is saved but **Project ID** is empty. |
| `Failed to get FCM access token` | The service account key was refused by Google. Paste a fresh key. |
| `FCM authentication failed (status 401, …)` | Google refused the access token. Check the key belongs to the project in **Project ID**. |
| `push_relay_server_id` is `null` in `fcm-config` | You left off `?platform=ios`, or registration hasn't succeeded yet. Check the log for the registration rows above. |
| The app errors when turning on push | The Firebase fields don't match your project. Check each against the table above, and against `fcm-config`. |
| One person gets nothing | They turned that kind of notification off, their community has push off, or their phone hasn't registered since push was turned on. Opening the app registers it. |

## Related

- [Configuration](configuration.md)
- [Email](email.md)
- [Notifications](../guides/notifications.md), from the user's side.
