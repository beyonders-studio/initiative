---
icon: lucide/lock-keyhole
---

# Sign-in and security

This page covers the parts of your account that decide how you get in: your email addresses, your password, the devices you're signed in on, and what happens when something changes that you didn't expect. You'll find them under **My Settings › Account** and **My Settings › Security**.

The other ways in have pages of their own: [passkeys](passkeys.md), [two-factor authentication](two-factor-authentication.md) and [API keys](api-keys-and-integrations.md).

## Add an email address

Any confirmed address on your account signs you in, and account mail goes to all of them. A second address is handy for the day you leave the job whose address you signed up with.

1. Open **My Settings › Account**.
2. Under **Email addresses**, type the address into **Add an address**.
3. Select **Add**.
4. Type your **Current password** and select **Add**.
5. Open the email that arrives at the new address and select its link.

Until you follow the link, the address shows as **Unconfirmed** and can't sign you in. Every address on your account hears about the new one once it's confirmed.

## Make another address your primary one

Password resets and sign-in codes go to your primary address first.

1. In **My Settings › Account**, select **Make primary** beside the address.
2. Type your **Current password** and select **Make primary**.

The change may [wait two days](#changes-that-wait) before it happens.

## Remove an email address

1. In **My Settings › Account**, select the remove button beside the address.
2. Type your **Current password** if asked, and select **Remove**.

The address stops signing you in and stops getting your account mail. You can't remove your primary address (make another one primary first), or the only confirmed address on your account. Removing a confirmed address may [wait two days](#changes-that-wait), and the address you removed is told.

No password on your account? Wherever this page says to type your current password, Initiative asks for a [fresh sign-in](#when-initiative-asks-you-to-prove-its-you) instead.

## Change your password

1. Open **My Settings › Security**.
2. Under **Password**, type your **Current password**.
3. Type the **New password**, at least 12 characters, and again in **Confirm password**.
4. Select **Change password**.

You stay signed in where you are. Every other browser and device is signed out, and your [API keys](api-keys-and-integrations.md) are switched off, so make new ones for anything that used them. If your server checks new passwords against known data breaches, one that has turned up in a breach is refused; pick another.

Signed in with a work or school account? Your password lives with your organization, so change it there.

## Set a password on an account without one

An account that signs in with a passkey, an emailed code or a work account may have no password. You can add one any time, as a second way in.

1. Open **My Settings › Security**.
2. Under **Set a password**, type a **New password** and again in **Confirm password**.
3. Select **Set a password**.

To give a password up and sign in with only a passkey, see [Go without a password](passkeys.md#go-without-a-password).

## See where you're signed in { #where-youre-signed-in }

**My Settings › Security › Where you're signed in** lists every browser and device with your account open. Each row says what it is, like "Chrome on macOS", and when it was last active. The one you're using is marked **This browser** or **This device**. Phone and desktop apps are listed under **Devices**, browsers under **Browsers**.

A browser stays signed in through 30 days of not being used, and the phone and desktop apps through 90, unless your server or a community sets something shorter.

### Sign out a browser you aren't using

1. In **Where you're signed in**, select **Sign out** beside the browser.
2. Select **Sign out** to confirm.

That browser has to sign in again. Everything else stays signed in.

### Remove a phone or computer

Use this for the phone that went in the lake.

1. In **Where you're signed in**, select **Remove device** beside it.
2. Select **Remove device** to confirm.

The app is signed out and nothing more is sent to it, including your messages. If it's ever signed in again, the messages only it held are deleted from it. A device marked **not signed in** still holds messages from an earlier sign-in; remove it once it's gone for good.

### Sign out everywhere else

For the laptop you borrowed at your mom's, and the library computer you've thought about twice since.

1. In **Where you're signed in**, select **Sign out everywhere else**.
2. Select **Sign out everywhere else** to confirm.

Every other session ends and you stay signed in here. Your API keys keep working; [delete them](api-keys-and-integrations.md#delete-a-key) separately if you need to.

## Changes that wait two days { #changes-that-wait }

Four changes to how you sign in can wait two days before they happen:

- making another address your primary one
- removing a confirmed address
- turning off two-factor authentication
- removing your last passkey

They wait when you make them from a browser you signed in on less than a day ago, or when it's the third change to your sign-in within an hour. A change made from the phone or desktop app, or after signing in with a passkey, happens straight away. If somebody else ever got into your account, two days is plenty of time for you to notice.

While a change waits, nothing about your account changes. Every confirmed address gets an email about it, with a link to cancel it, and **A change is waiting** sits at the top of **My Settings › Account** and **My Settings › Security**:

- **Cancel the change** calls it off.
- **Make it now with a passkey** skips the wait, if you have a passkey.

Only one change waits at a time. Ask for another and you're pointed at the first.

## If you didn't make a change { #this-wasnt-me }

Every email about a change to how you sign in has a **This wasn't me** button: a new address, passkey, password or set of recovery codes, two-factor authentication switched off, or a sign-in provider newly linked to your account.

1. Select **This wasn't me** in the email.
2. On **Wasn't you?**, select **Sign out everywhere**.

Your account is signed out on every browser, phone and computer, and its API keys are switched off. On its own, that changes nothing else.

When a change looks out of place (not made with a passkey, from a browser signed in less than a day, or one of several in a row), the page can also undo it. **Undo it and sign out everywhere** takes an added address or passkey back off, moves your primary address back, or puts a removed address back on. For a change that's [still waiting](#changes-that-wait), **Cancel it and sign out everywhere** stops it. **Only sign out everywhere** leaves the change alone. Each link works once, for a week.

Then sign in again and check your addresses, passkeys and two-factor authentication under **My Settings › Security**. Can't sign in? [Reset your password](../getting-started/signing-in.md#reset-a-forgotten-password).

## When Initiative asks you to prove it's you

Some changes ask for your current password. An account without one is asked to have signed in within the last 10 minutes. If you signed in longer ago than that, **Prove it's you** appears:

- **Use your passkey** signs you in again with your passkey.
- **Email me a code** sends a code. Type it under **Code from your email** and select **Continue**.
- **Sign in again** signs you out so you can sign back in.

Then try the change again.

## Report a security problem

If your server takes security reports, **My Settings › Security** ends with **Report a security problem**. Use it when something about the server looks wrong, or when somebody else got into your account.

1. Select **Report a security problem**.
2. Under **What is it about?**, pick **A weakness in this server**, **Someone else got into my account** or **Something else**.
3. Describe it under **What did you find?**
4. Select **Send report**.

The people who run the server read it, and you can follow it under **My Tickets**. A problem with the Initiative software itself goes to the project; see [Security](../security/index.md).
