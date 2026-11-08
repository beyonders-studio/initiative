---
icon: lucide/shield-check
---

# Two-factor authentication

Two-factor authentication adds a second thing to signing in: a six-digit code from an app on your phone, which changes every 30 seconds. After your password or emailed code, Initiative asks for the code too. It takes about two minutes to set up, and it's the biggest single improvement you can make to your account's security.

Signing in with a passkey or your work account doesn't ask for the code. A community or your server can still ask for a second factor, though, and the code from your app answers that wherever you signed in from.

You'll need an authenticator app. Google Authenticator, Microsoft Authenticator, 1Password, Bitwarden and Ente Auth all do the same standard thing, so if you already use one for your bank, use that one. If **My Settings › Security** has no **Two-factor authentication** section, your server doesn't offer it.

## Set up two-factor authentication

1. Open **My Settings › Security**.
2. Under **Two-factor authentication**, select **Set up two-factor authentication**.
3. Type your **Current password** and select **Continue**.
4. Scan the square code with your authenticator app.
5. Type the six digits your app shows into **Code from your app**.
6. Select **Turn on**.
7. Save your recovery codes, with **Copy codes** or a pen and paper.
8. Select **Done**.

Can't scan the square because you're on the desktop app, or your camera is cracked? Type the key under **Can't scan it? Enter this key instead:** into your app.

No password on your account? Initiative skips step 3, as long as you signed in within the last 10 minutes; otherwise it asks you to [prove it's you](sign-in-and-security.md#when-initiative-asks-you-to-prove-its-you) first.

!!! warning "Save those recovery codes"
    You get ten recovery codes, and they're the only way into your account if your phone is lost, broken or wiped. Keep them somewhere that isn't your phone: a password manager, a file on your laptop, or a piece of actual paper in an actual drawer. You won't be shown them again.

From then on, signing in asks for your password or emailed code, then **One more step** with the code from your app. The phone and desktop apps ask too.

## Sign in without your phone

1. Sign in with your password or emailed code as usual.
2. On **One more step**, select **Use a recovery code**.
3. Type one of your recovery codes and select **Continue**.

Each code works once. **My Settings › Security** shows how many you have left, and the count turns red when you're down to three.

## Get new recovery codes

Do this when you've used a few, or if you've ever been unsure where the old list ended up.

1. Open **My Settings › Security**.
2. Under **Two-factor authentication**, select **New recovery codes**.
3. Type your **Current password** and select **Continue**.
4. Save the new codes.
5. Select **Done**.

The old codes stop working straight away.

## Turn off two-factor authentication

1. Open **My Settings › Security**.
2. Under **Two-factor authentication**, select **Turn off**.
3. Type your **Current password**.
4. Type a code from your app, or a recovery code, into **Code from your app, or a recovery code**.
5. Select **Turn off**.

Signing in stops asking for the code, your recovery codes are thrown away, and your other devices are signed out. If you're turning it off because something went wrong, that last part is the useful one. Turned off from a browser you signed in on recently, it [waits two days](sign-in-and-security.md#changes-that-wait) before it happens.

If your server requires a second factor, turning yours off means being asked for one again on your very next click.

## If you've lost your phone and your recovery codes

Ask whoever runs your Initiative. They can [clear two-factor authentication](../running-a-server/platform-roles.md#managing-platform-users) from your account, which signs you out everywhere and emails you. Then you sign in the way you usually do and set it up again on your new phone.

They can only take it off. Nobody, at any level, can see your key or your recovery codes, because there's nothing to look up.

## When your server or a community requires it

Whoever runs your server can require a second factor for everybody, or only for people with server-wide roles. A community can require one each time you open it. Either way, you're asked where you are, with a link to set one up if you don't have one, and a [passkey](passkeys.md) counts as well as an authenticator app. [Signing in](../getting-started/signing-in.md#when-a-community-asks-you-to-sign-in-again) walks through each prompt.

While your server requires one and you haven't set it up, your [API keys](api-keys-and-integrations.md) and the phone app stop working, because neither can type a code. Both come back on their own once you have a factor.

??? techspec "The details"
    Standard TOTP (RFC 6238): SHA-1, six digits, 30-second steps, which is what every authenticator app expects. Codes one step either side of the current one are accepted, so a phone clock that has drifted slightly still works.

    Each code is accepted once. Presenting the same code twice, even inside its 30 seconds, gets you in once, which is why signing in right after setup may mean waiting for the next code.

    Recovery codes come in sets of ten, stored only as hashes. The key is encrypted at rest. Neither is readable by anybody, including whoever runs the server.
