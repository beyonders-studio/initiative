---
icon: lucide/mail
---

# Email

Initiative sends mail through an SMTP server you point it at: your own, or a transactional email service. The [owner](platform-roles.md) sets it up under **Settings → Platform → Email**, and it takes effect when saved.

Set it up before anybody forgets a password, rather than after. Without it Initiative works fine, and the bell in the app carries every notification, but nothing below gets sent.

## What Initiative sends

| Kind | What | Follows notification settings |
|---|---|---|
| Account mail | Sign-up and sign-in codes, address confirmations, password resets, and notices an account gets about itself: a password, passkey, second factor or address changed, recovery codes issued, sign-in locked, the account erased | No. It always goes. |
| Community notices | A community you run deleted, or put on hold with the date it will be deleted | No |
| Notifications | Mentions, assignments, reactions, direct messages, being added to an initiative or project, access requests, join requests | Yes |
| Digests | The coming-up and overdue summaries people choose for themselves | Yes |

Notification mail follows each person's own choices, and the server-wide **Email notifications** switch in [What notifications may carry](configuration.md#what-notifications-may-carry) can turn all of it off. Account mail ignores both, so nobody is ever locked out of their own account. Mail goes out in each person's language, with your branding's accent color and the logo built in rather than fetched.

**Ways in** refuses **Email OTP** until a mail server is set up, since the code has nowhere to go. See [Single sign-on](single-sign-on.md).

## Settings

![The Email tab under Settings → Platform](../images/running-a-server/email-settings.png)

| Field | What it takes |
|---|---|
| **Host** | Your SMTP server, such as `smtp.mailprovider.com`. Required. |
| **Port** | Usually `587`, `465` or `25`. Blank means `465` with **Secure (TLS) connection** on and `587` with it off. |
| **Secure (TLS) connection** | On, the connection is encrypted from its first byte, which is what port `465` expects. Off, Initiative connects in the clear and switches to encryption with STARTTLS when the server offers it, which is what `587` and `25` expect. |
| **Reject unauthorized certificates** | On, the server's certificate must be valid for its name. Turn it off only for a relay you fully trust that has a certificate nothing vouches for, such as a self-signed one on your own network. |
| **Username** / **Password** | Your SMTP credentials. Initiative signs in only when both are filled in. The password is stored encrypted and never shown again; leave it blank when editing to keep the saved one. |
| **From address** | The sender people see, such as `Initiative <no-reply@example.com>`. Required. |
| **Test email recipient** | Where **Send test email** sends to. |

Until **Host** and **From address** are both saved, Initiative sends nothing and queues nothing.

## Test it before you rely on it

1. Fill in the fields and select **Save email settings**.
2. Type your own address in **Test email recipient**.
3. Select **Send test email**.

The test uses the saved settings, so save first. If **Test email sent** appears and the mail arrives, you're done.

If it says **Unable to send test email**, check the host, port and TLS combination before anything else. It is almost always the host, port and TLS combination. Credentials come second. The server log has a line naming the error's type and the mail server's reply code, never the message itself.

!!! tip "Arrived, but in spam?"
    That's your mail domain's SPF, DKIM and DMARC records, which your mail service's own instructions cover. Initiative only hands the message over.

## Setting it from the environment

On a server's first start, the `SMTP_*` variables fill these fields in, so a deployment tool can bring it up with mail working. After that the tab owns them and the variables are ignored. See [Read on the first start only](configuration.md#read-on-the-first-start-only).
