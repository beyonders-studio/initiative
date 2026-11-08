---
icon: lucide/lock
---

# Private messages

Direct messages in Initiative are end-to-end encrypted. A message is encrypted on the device that sends it and decrypted on the devices it's sent to. The server carries it but holds no key that could read it, and neither does anybody who runs the server.

This page covers what that protects, what the server can see, and why your message history stays on your devices. For using messages day to day, see [Messages](../guides/messages.md).

## What stays private

What you write. The keys that decrypt a message exist only on the devices in the conversation. No setting in a community or on the server opens a conversation, and no recovery key is held anywhere.

## What the server can see

The server has to know where to deliver a message, so it keeps:

- **Each conversation's members**, when it started, and when each member joined and accepted it.
- **Each device on an account**: its public keys, a label for the browser or app it runs in, when it was added, and when it last collected messages.
- **Messages waiting to be collected**: for each, the conversation, the device it's for, and the encrypted text. The sender isn't stored with it.
- **Unread message alerts in the bell**: who sent them and how many.
- **Your account details**: your handle, your email addresses, and when you joined.

Encryption hides what was said. The server can see who is in a conversation with whom, and when they're active. If that fact is the sensitive part, decide who can reach you (below).

## What isn't kept

**A message leaves the server once it's collected.** When a device confirms it has received a message, the server deletes its copy for that device. A message nobody has collected waits with no time limit, up to 50 MiB of waiting messages per account. Waiting messages are also deleted when their device is removed, an hour after a browser's session ends, and when the account is erased.

**Nothing reads the text.** The server never decrypts a message, so it can't search or scan one. Search in **My Messages** runs on your device and matches people's handles and group names.

## Notifications about messages

A push notification or email about a new message names the sender and never carries the message. A push reads *"Sam sent you a message"* with *"Open Initiative to read it."* An email names the sender and says the contents can't be included. Where the server hides notification details, the push reads *"A message or a connection request"* and names nobody.

Push notifications pass through Apple or Google. For the published app they go through the project's push relay first; see [Push notifications](../running-a-server/push-notifications.md).

## On your device

Each device keeps its own copy of your conversations, in the browser's or app's storage (IndexedDB). The encryption keys are stored encrypted under a key the browser won't let anything export. Initiative doesn't encrypt the messages themselves a second time on the device, so they're as private as the device is.

Signing out of Initiative in a browser deletes that browser's copy and removes it from your devices. The phone and desktop apps keep their copy when you sign out, so signing back in on the same device shows your conversations straight away.

## Why history stays on your devices

The server keeps no readable archive of your conversations, so a new device can't download your past messages from it. A device that wasn't there has no older messages, and signing out of a browser takes its copy with it. See [Messages](../guides/messages.md).

History can move between devices in two ways, both sent as ordinary encrypted messages:

- **To a new device of your own.** When you verify it from a device you already use, that device can send it your history, if you choose **Send it my message history**.
- **To somebody who accepts a group conversation late.** Each member's device sends them that member's own messages. Their device waits up to 24 hours for the other members to come online.

The server carries these like any other message and deletes them once they're collected.

## Messages aren't community content

Messages belong to the people in them, not to any community.

- No community export or search includes them.
- Community admins and moderators have nothing in them to read or moderate.
- Whoever runs the server can turn messaging off for everyone with **Let people message each other**. That hides **My Messages** and refuses new messages. Nothing is deleted, so turning it back on restores conversations and connections.

If somebody is behaving badly, report their account from their profile. That report goes to whoever runs the server. See [Reporting a problem](reporting-a-problem.md).

## Who can reach you

The controls belong to the people in the conversation:

- **Direct messages**, under **My Settings → Privacy**, says who can ask to message you outside your connections: **Private** (no one), **My communities** or **Anyone**. A new account starts on the server's default, which is **Private** unless whoever runs the server changes it.
- **Ignore** an account and nothing it sends you arrives: messages, message requests or connection requests. Nothing is deleted, and the other person isn't told.
- Messaging is for people aged 16 and over, on a server that asks members their age.

## How the encryption works

- Messages use Olm, an implementation of the Double Ratchet, through vodozemac, an audited Rust library. It's compiled to WebAssembly and runs in a separate worker inside the app.
- No key is shared between more than two devices, in a group included. A group message is encrypted separately for each device it's going to, on that pair's own session, so there is no group key.
- Every device signs its own keys. The server checks the signature when a device registers, and each app checks it again before it encrypts anything to that device.
- Your devices encrypt nothing to a new device on your account until you verify it from one of them. Both screens show four pictures, drawn from keys made for that one attempt, and you confirm on both that they match. An attempt lasts up to 10 minutes.
- You verify only your own devices. When somebody you talk to adds or changes a device, the conversation shows a line saying so.
- There's no recovery key, key backup or escrow.
- The code is open source, like the rest of Initiative: `crypto/` holds the Rust library, and `frontend/src/crypto/` the app's side of it.

## Related

- [Messages](../guides/messages.md): using them day to day.
- [Data & compliance](data-and-compliance.md#what-could-be-handed-over): what exists to be handed over.
- [How your data is kept separate](how-your-data-is-kept-separate.md): how everything else is kept apart.
