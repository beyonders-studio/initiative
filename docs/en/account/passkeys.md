---
icon: lucide/fingerprint
---

# Passkeys

A passkey signs you in with nothing to type. Your phone, laptop or password manager holds a key, and you unlock it with the fingerprint, face or PIN you already use for the device. There's no password to remember and nothing to misspell at eleven at night.

Passkeys appear in **My Settings › Security** when your server offers them. If there's no **Passkeys** section, it doesn't.

## Add a passkey

1. Open **My Settings › Security**.
2. Under **Passkeys**, select **Add a passkey**.
3. Give it a **Name** you'll recognize in a list, like "Laptop", "Phone" or "The blue key on the lanyard".
4. Type your **Current password**, if asked.
5. Select **Continue**.
6. Follow the prompt that appears, and unlock it the way you unlock the device.

The new passkey joins the list with the date you added it. No password on your account? Initiative asks for a [fresh sign-in](sign-in-and-security.md#when-initiative-asks-you-to-prove-its-you) at step 4.

Where the key is kept is up to your browser or phone, which asks where to save it. A passkey marked **Synced** lives in a password manager or your phone's keychain, so it's on your other devices too and losing one device doesn't lose it. One without that mark lives on the device that made it, so add another for each device you use. You can have up to 20.

The prompt comes from different places depending on where you are. In a browser and the Android app, your browser or phone asks directly. The Windows app opens Windows' own passkey window, which offers Windows Hello, your phone or a security key. The Mac and Linux apps open your browser for a moment and hand you back.

## Sign in with a passkey

Select **Sign in with a passkey** on the sign-in card, or click into the **Email** box and pick your passkey from the browser's list. [Signing in](../getting-started/signing-in.md#sign-in-with-a-passkey) has the details for each app.

## Rename a passkey

1. In **My Settings › Security**, select **Rename** beside the passkey.
2. Type the new **Name**.
3. Select **Save**.

The name is only for you, so you can tell your passkeys apart.

## Remove a passkey

When a device is gone, remove its passkey.

1. In **My Settings › Security**, select **Remove** beside the passkey.
2. Type your **Current password**, if asked.
3. Select **Remove**.

That passkey stops signing you in, and nothing on the lost device can add it back. Not sure which one was the lost phone? Each passkey says when it was last used, and the one that stopped is the one that went.

You can't remove your last way in, so your only passkey stays until you set a password or add another. Removing your last passkey may [wait two days](sign-in-and-security.md#changes-that-wait) before it happens.

## Go without a password

Once you have a passkey, the password is optional. Giving it up has to happen in a browser, not the phone or desktop app.

1. Open **My Settings › Security** in a browser.
2. Under **Password**, select **Remove your password**.
3. Type your **Current password**.
4. Select **Remove your password**.
5. If Initiative shows recovery codes, save them somewhere that isn't the device with your passkey, then select **Done**.

From then on your passkey is how you get in, and you're signed out everywhere else. You're shown ten fresh recovery codes if you held fewer than three, and any old ones stop working. They're shown once.

Those codes are the way back if the passkey is ever lost: [set a password with a recovery code](../getting-started/signing-in.md#set-a-password-with-a-recovery-code), sign in with it, add a fresh passkey, and remove the password again if you like. **My Settings › Security** shows how many codes you have left, under **Two-factor authentication**, with **New recovery codes** to replace the set.

## When a community asks for a passkey

A community can require everyone in it to have signed in with a passkey. If you signed in some other way, a box asks for your passkey when you open that community. Select **Use your passkey** and unlock it, and everything fills in behind it. Nobody is signed out to satisfy a new rule. No passkey yet? Select **Add a passkey**, add one, and come back.

## If you can't add a passkey

The message under **Passkeys** says what's wrong:

| Message | What to do |
|---|---|
| "This browser can't make a passkey" | Use an up-to-date browser. |
| "This device or password manager already holds a passkey for this site" | You already have one there. Use it, or save the new one somewhere else. |
| "This account holds as many passkeys as it can" | Remove one you don't use. |
| "Passkeys need this site to have a proper domain name and https" | Ask whoever runs the server. |
| "A passkey can't be made at this address" | You opened Initiative at a different address from the one it's set up under. Ask whoever runs the server. |

??? techspec "The details"
    WebAuthn, through the reference libraries on both sides. Credentials are requested as discoverable (resident key preferred), so a sign-in can start from the key rather than from a typed address. Every ceremony requires user verification: a passkey that can't prove the person as well as the device is not registered or accepted.

    The relying party is the host of the deployment's own address (`APP_URL`), and the origin must match it exactly. Each credential records the host it was made under, so a deployment that moves to a new address refuses its old passkeys and records a plain reason in the audit log rather than a signature that doesn't verify. A passkey sign-in is recorded as a multi-factor cryptographic authenticator: `hwk` for a device-bound key, `swk` for a synced one, plus `mfa`. That's what a community requiring a second factor reads.

    Only public keys are stored, with the authenticator's signature counter, which must never go backwards. No attestation is requested or kept. An account holds at most 20 passkeys.

    The Android app runs the ceremony through the platform's credential manager. The server names the app in `/.well-known/assetlinks.json` and accepts the origin Android reports for it (the hash of the app's signing certificate) beside its own address. Where the phone won't confirm that association, the app uses the system browser.

    The Windows app runs each ceremony in a page of its own, laid over the app and loaded at the deployment's address, so the origin the server checks is the deployment's own and Windows shows its own passkey dialog. Where Windows can't use the address, the app uses the system browser.

    In the browser hand-off, only the prompt leaves the app. The app begins the ceremony, opens the deployment's own page in the system browser with the options in the address's fragment, and that page runs the prompt and hands the credential back through `initiative://passkey/callback`. The app then finishes the ceremony itself. A sign-in or sign-up begun this way carries a PKCE challenge (RFC 7636), and its finish carries the verifier.
