---
icon: lucide/megaphone
---

# Announcements

An **announcement** is a notice shown to the people using your server — a dialog that appears in front of somebody who didn't ask for it. That makes it a strong tool and a blunt one, so it's worth being clear about when it's the right one.

Use an announcement when somebody has to **act**, or would otherwise be **confused**: a change that breaks how they worked yesterday, a setting that moved, a maintenance window they need to plan around. Anything smaller belongs in the release notes, where people go looking for it.

## Where they come from

There are two sources, and they read identically to whoever receives them.

| | **Written here** | **Shipped with Initiative** |
|---|---|---|
| Who writes it | An operator or owner on your server | The Initiative team, as part of a release |
| What it's for | Anything about *your* deployment — "we're upgrading on Sunday" | Something every deployment needs to hear |
| Where to edit it | **Operator dashboard → Announcements** | Nowhere — it arrives with the version |

Shipped announcements are marked **Built in** in the list. You can preview one to see exactly what your users get, but you can't edit or delete it; it retires when a later release drops it.

## Writing one

Open **Operator dashboard → Announcements** and choose **New announcement**. You need the *manage announcements* capability, which operators and owners have — see [Platform roles](platform-roles.md).

An announcement is a **title** plus one or more **sections**. Each section has an optional heading, a body in Markdown, and optionally a picture with alt text. Add sections in the order you want them read; the arrows move one up or down.

![The announcement editor](../images/running-a-server/announcement-editor.png)

### Turning it into a wizard

Tick **Start a new page** on a section and everything from there onward moves to a second page, with **Next** and **Back** to step through it. Use this when a notice has genuinely separate beats — "what changed", then "what to do about it" — rather than to break up a long paragraph.

### Preview before you publish

**Preview** on any announcement shows the reader's dialog exactly as they'll get it, page breaks and all. Use it before publishing — an announcement is shown once, so there's no quiet second attempt.

## Choosing who sees it, and when

Every one of these settings **narrows** the audience. The default is "everybody, immediately", which is usually wrong for something worth interrupting people over.

| Setting | Use it when |
|---|---|
| **Minimum platform role** | The thing that changed sits behind a platform rung — only support staff or operators can act on it. |
| **Community admins only** | Only people who administer a community can do anything about it. |
| **Accounts this is for** | The notice is about a transition. *Accounts that existed when it was published* for a change people lived through; *accounts made since* for a tip aimed at somebody just arriving; *everyone* for news that stands on its own. |
| **Publish at** | You want it to go out later. Leave it empty and it stays a **draft**, visible only to you. |
| **Stop showing at** | It stops being true on a date. An end date also takes it off the announcements page. |
| **Show on page** | It explains a screen. Give it a path pattern and the notice waits until somebody opens a matching page, instead of queueing up at sign-in. |
| **Times to acknowledge** | Missing it would cost somebody real work. It comes back until they've dismissed it that many times. Keep it at 1 unless you mean it. |

### Path patterns

**Show on page** takes a path, starting with `/`. Two wildcards are available:

- `*` stands for **one** part of the path — `/c/*/settings` matches any community's settings page.
- `**` stands for **the rest** of the path, so nothing may follow it.

A pattern with a space in it, or a `*` glued to other characters, is rejected as you type.

### Categories

The **category** sets the label and colour on the dialog and in the archive: **Release**, **New**, **Breaking change**, **Maintenance**, **Security**, or **Announcement**. Pick the one that tells a reader how much attention to pay.

## What readers get

- The dialog appears the next time they use Initiative — or, with a path pattern, when they reach that page.
- **Got it** dismisses it. It comes back only if you asked for more than one acknowledgement, and the dialog says so ("shows once more").
- Pictures open **full size** on a click.
- Every notice they close leaves a line in their notifications, already read, that opens it again until the notice reaches its end date or the line clears itself 30 days later.

!!! screenshot "The announcements archive"
    **Show:** the archive page with a mix of read and unread notices, and the unread filter.

    Save as `en/images/running-a-server/announcements-archive.png`, then replace this box with:
    `![The announcements archive](../images/running-a-server/announcements-archive.png)`

## Editing, unpublishing and deleting

- **Editing** a live announcement changes it for everyone who hasn't read it yet. People who already dismissed it don't see it again.
- **Back to draft** takes a published announcement out of circulation without losing it.
- **Deleting** removes it along with everyone's record of having read it. If you delete and re-create the same notice, people who already dealt with it will be shown it again — edit the original instead.

!!! note "Announcements aren't translated"
    Sections are written once and shown as you wrote them, whatever language the reader has the interface set to. Only the dialog's own buttons follow their language. Write plainly, and keep it short.

## Related

- [Platform roles](platform-roles.md) — who can write announcements.
- [Configuration](configuration.md) — server-wide settings.
- [Notifications](../guides/notifications.md) — the other way Initiative tells people things.
