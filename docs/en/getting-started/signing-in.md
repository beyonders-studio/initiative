---
icon: lucide/log-in
---

# Signing in

Signing in takes about four seconds. Your server decides which ways in it offers, so your sign-in card shows some or all of the ones below. Initiative keeps you signed in on each device, so you aren't doing this every morning like it's your bank.

## Sign in with your email and password

1. Open your group's Initiative address.
2. Type your **Email** and **Password**.
3. Select **Sign in**.

If you've set up [two-factor authentication](../account/two-factor-authentication.md), the card asks for **One more step**:

1. Type the **Authentication code** from your authenticator app.
2. Select **Continue**.

Phone in another room? Select **Use a recovery code** and type one of the codes you saved. **Start over** goes back to the email and password.

## Sign in with a passkey

If you've [added a passkey](../account/passkeys.md):

1. Select **Sign in with a passkey**.
2. Unlock it the way you unlock your phone or computer.

Many browsers also offer your passkey the moment you click into the **Email** box, above the addresses they remember. Pick it there and you skip the button.

In the Android app, the prompt comes from your phone. In the Windows app it's Windows' own passkey window, and **Use a passkey saved in your browser** under the button reaches passkeys kept in a browser's password manager. In the Mac and Linux apps, your browser opens for a moment and hands you back.

## Sign in with a code by email

No password to remember, and nothing to reset.

1. Select **Email me a code**.
2. Type your **Email** and select **Email me a code**.
3. Type the code from your inbox and select **Sign in**.

The code works for 10 minutes. Five wrong tries and it gives up, so ask for a fresh one. If your account has two-factor authentication, the code from your app comes next.

Don't have an account yet? The same button makes one. After the code, Initiative asks you to **Choose a username**, and **Create account** finishes it.

## Sign in with your work or school account

1. Select **Continue with** and your organization's name.
2. Sign in the way you do everywhere else at work or school.

You come back to Initiative signed in; in the phone or desktop app, your browser opens for this and hands you back. The first time, Initiative may ask you to choose a username and agree to your server's terms; see [Sign up with your work or school account](create-account.md#sign-up-with-your-work-or-school-account).

## Sign in from your community's own sign-in link

Some communities give their members a sign-in link of their own, with a button for each of the community's sign-in providers.

1. Open the link your community admin shared.
2. Select **Continue with** and the provider's name.

**Use another sign-in method** goes to the ordinary sign-in card. This link works in a browser; in the app, sign in from the app's own card.

## Reset a forgotten password

It happens to everybody, roughly monthly. There is no shame here.

1. On the sign-in card, select **Forgot password?**
2. Type the **Email** your account uses and select **Send reset link**.
3. Open the email and select its link.
4. Type a **New password** of at least 12 characters, and again in **Confirm password**.
5. Select **Reset password**.
6. Select **Go to sign in** and sign in with the new password.

The link works for an hour, so one that's been sitting in your inbox since Tuesday won't. Nothing arrived? Check spam, then ask for another. Resetting your password signs you out on every other device and turns off your [API keys](../account/api-keys-and-integrations.md).

## Set a password with a recovery code

This is for an account that has no password, because it signs in with a passkey, and the passkey has gone off with the phone. You'll need one of the recovery codes you saved when the password went away.

1. On the sign-in card, select **Forgot password?**
2. Select **No password to reset? Use a recovery code**.
3. Type your **Email** and one **Recovery code**.
4. Type a **New password**, and again in **Confirm password**.
5. Select **Set password**.
6. Sign in with your new password.

Each recovery code works once. Once you're back in, you can [add a passkey](../account/passkeys.md#add-a-passkey) and give the password up again.

## When a community asks you to sign in again

A community can ask for more than your server does. When you open one of those, a box appears where you are, and nobody signs you out.

| The box says | Do this |
|---|---|
| **Additional sign-in required** | Select **Sign in with** and the provider's name, and sign in there. |
| **One more step for this community**, asking for a code | Type the code from your authenticator app and select **Continue**. |
| **One more step for this community**, asking for a passkey | Select **Use your passkey** and unlock it. |

Don't have the code or passkey it wants? Select **Set one up** or **Add a passkey**, add one in your settings, then come back. **Not now** closes the box, and the community stays closed until you answer it.

## When your server asks for a second factor

Whoever runs your server can require two-factor authentication for everybody, or for people with server-wide roles. If that's you and you haven't set one up, Initiative asks the next time you open it. Set up an [authenticator app](../account/two-factor-authentication.md) or a [passkey](../account/passkeys.md), and you're back where you were in about a minute.

Until you do, your API keys and the phone app stop working for you, because neither can type a code. Both start working again the moment you have a factor.

## Sign in on the phone or desktop app

The app asks which server it's talking to the first time, because there are a lot of Initiatives out there and it can't guess yours. [Connect the app to your server](install-the-app.md#connect-the-app-to-your-server) covers that step, then you sign in the same ways as above.

## Sign out

1. Select your name or picture at the bottom of the sidebar.
2. Select **Sign out**.

On a shared or public computer, do this every time. The library computer does not need standing access to your PTA. To sign out somewhere you aren't sitting, use [Where you're signed in](../account/sign-in-and-security.md#where-youre-signed-in).

## If your account is suspended

A platform moderator can suspend an account. You can still sign in, but you see **Your account is suspended** in place of your communities, with the reason if one was given. Nothing has been removed, and it all comes back when the suspension is lifted.

To ask for it to be lifted:

1. Select **Appeal**.
2. Explain under **Why should it be lifted?**
3. Select **Send appeal**.

The moderators can write back on that same page.

Next, find your way around with [the quick tour](a-quick-tour.md).
