---
icon: lucide/fingerprint
---

# Passkeys

A passkey is a sign-in with nothing to type. Your phone, your laptop or your password manager holds a key; the site asks it a question; you prove it's you with the fingerprint, face or PIN you already unlock the device with; done. No password, no code from an app, nothing to remember and nothing to spell wrong at eleven at night.

## Adding one

1. **My Settings → Security → Passkeys → Add a passkey**.
2. Give it a name you'll recognise in a list — *Laptop*, *Phone*, *The blue key on the lanyard*.
3. Confirm your password. No password on your account, or none on your server? Then it asks you to prove it's you with a fresh sign-in.
4. Your browser takes over from here (in the Android app it's your phone, and in the Windows app it's Windows): it asks where to keep the key and how you'd like to prove it's you. Say yes to whatever you normally unlock with.

That's it. It's in the list, with the date you added it.

Where the key ends up is your browser's decision, not ours. Signed in to a password manager or the phone's own keychain? It probably goes there, and shows up as **Synced** in the list — meaning the same key is now on your other devices too, and losing this one doesn't lose it. Not synced? It lives on that device and nowhere else, so add another for the next one. You can have twenty.

## Signing in with it

On the sign-in screen, press **Sign in with a passkey**, or just click into the email box — most browsers offer your passkeys right there, above the addresses they've remembered. Prove it's you, and you're in.

In the Android app, the button asks your phone directly: same fingerprint, same face, and you never leave the app. The Windows app does the same through Windows' own passkey window, which offers Windows Hello, your phone or a security key. On an iPhone, a Mac or Linux, or on a server the app can't sign in to this way, it opens your browser for a moment, because that's where your passkeys live, and hands you straight back once you've unlocked one.

Keep your passkeys in a browser's password manager? In the Windows app, **Use a passkey saved in your browser**, just under the button, sends that one sign-in to your browser, where they are.

## When a device goes

Remove its passkey: **My Settings → Security → Passkeys**, the bin next to the name, and your password (or a fresh sign-in) to confirm. Sign in with your password or another passkey first if you need to. Nothing on the lost device can add one back.

Not sure which one was the lost phone? The list says when each was last used. The one that stopped is the one that went.

## Going without a password

Once a passkey is in the list, the password is optional. **My Settings → Security → Password → Remove your password** — from a browser, not the phone app — takes it away for good: from then on the passkey is how you get in, every other device is signed out, and you're shown ten **recovery codes**, once, unless you already hold a full set. If you were down to your last couple, a fresh ten replaces them, and the old ones stop working.

Keep those somewhere that isn't the device with the passkey on it. They're the way back if the passkey is ever gone: on the sign-in screen, **Forgot password? → Use a recovery code**, and you set a new password with one. Then you're an account with a password again, free to add a fresh passkey and take the password away once more.

You can't remove the last way in. Your only passkey stays until you set a password or add another, and your password stays until there's a passkey to replace it.

Removing your last passkey from somewhere you've only just signed in [waits two days](profile-and-preferences.md#changes-that-wait) before it happens.

## If a community asks for one

A community can require that everybody in it signed in with a passkey, the same way it can require a code from an authenticator app. Signed in with your password instead? You're asked for the passkey where you are — a small prompt, then everything fills in behind it. Nobody is signed out to satisfy a new rule.

The Android and Windows apps ask for it right there in the app. On an iPhone, a Mac or Linux, the prompt sends you to a browser to present it.

??? techspec "The details"
    WebAuthn, through the reference libraries on both sides. Credentials are made as discoverable, so a sign-in can start from the key rather than from a typed address, and every ceremony requires user verification: a passkey that cannot prove the person as well as the device is not one this site will register or accept.

    The relying party is the host of the deployment's own address, and the origin must match it exactly. Each credential records the host it was made under, so a deployment that moves to a new address refuses its old passkeys and records a plain reason in the audit log rather than a signature that does not verify. A sign-in through a passkey is recorded as a multi-factor cryptographic authenticator — `hwk` for a device-bound key, `swk` for a synced one, and `mfa` — which is what a community requiring a second factor reads.

    Public keys only are stored, alongside the authenticator's counter, which must never go backwards. No attestation is requested or kept.

    The Android app runs the ceremony through the platform's credential manager. The server names the app in `/.well-known/assetlinks.json` and accepts the origin Android reports for it, the hash of the app's signing certificate, beside its own address. Where the phone won't confirm that association, the app uses the system browser.

    The Windows app runs each ceremony in a page of its own, laid over the app and loaded at the deployment's address, so the origin the server checks is the deployment's own and Windows shows its own passkey dialog. Nothing is fetched for that page. Where Windows can't use the address, the app uses the system browser.

    The server answers `/.well-known/apple-app-site-association` once the iPhone app is published. Until then the iPhone app runs every ceremony in the browser, on every server.
