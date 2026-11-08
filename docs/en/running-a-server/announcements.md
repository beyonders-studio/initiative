---
icon: lucide/megaphone
---

# Announcements

An announcement is a dialog that appears in front of somebody who didn't ask for it, which makes it a strong tool and a blunt one. Use one when people have to act, or would otherwise be confused: a change that breaks how they worked yesterday, a setting that moved, a maintenance window to plan around. Anything smaller belongs in the release notes, where people go looking for it, and not in a pop-up between them and their task list.

## Where they come from

Two sources, and they look identical to whoever reads them.

| | Written on your server | Built in |
|---|---|---|
| Who writes it | An operator or owner | The Initiative project, as part of a release |
| What it's for | Anything about your server, such as "we're upgrading on Sunday" | Something every server needs to hear |
| Where to edit it | **Operator dashboard › Announcements** | Nowhere. It arrives with a version and retires when a later one drops it. |

Built-in ones are marked **Built in** in the list. **Preview** shows exactly what your users get, and that's all you can do with one. A built-in notice can also be limited to servers that upgraded from below a given version, so a fresh install that never had the old behavior isn't told about the change.

## Writing one

Operators and owners can write announcements; it's the `announcements.manage` capability in [Platform roles](platform-roles.md).

1. Open **Operator dashboard › Announcements**.
2. Select **New announcement**.
3. Fill in **Title** and choose a **Category**.
4. Under **Sections**, write the first section. Select **Add section** for each further one.
5. Choose who sees it and when, below.
6. Select **Preview** to see the reader's dialog, then **Save**.

![The announcement editor](../images/running-a-server/announcement-editor.png)

Each section has an optional heading, a body in Markdown, and optionally a picture with alt text for screen readers. The arrows move a section up or down, and the bin removes it.

| Part | Limit |
|---|---|
| **Title** | 200 characters |
| Sections | 1 to 20 |
| A section's heading | 160 characters |
| A section's body | 4,000 characters of Markdown |
| A picture | PNG, JPEG, WebP or GIF, up to 2 MB and 4096 × 4096 pixels |
| A picture's alt text | 200 characters |

A picture you upload and then don't use is removed a day later.

### Turning it into a wizard

Tick **Start a new page** on a section, and everything from there on moves to a page of its own. The reader steps through with **Continue** and **Back**, and sees which page they're on. Use it when a notice has separate beats, such as what changed and then what to do about it, rather than to break up a long paragraph.

### Categories

The **Category** sets the label and color on the dialog: **Release**, **New**, **Breaking change**, **Maintenance**, **Security** or **Announcement**. Pick the one that tells a reader how much attention to pay.

## Choosing who sees it, and when

Every one of these narrows the audience. The default is everybody, immediately, which is usually wrong for something worth interrupting people over.

| Setting | What it takes | Use it when |
|---|---|---|
| **Minimum platform role** | **Everyone**, **Moderator**, **Support**, **Operator** or **Owner**: that rung of the [ladder](platform-roles.md) and above | The thing that changed sits behind a platform rung, so only support staff or operators can act on it. |
| **Community admins only** | On or off | Only people who administer at least one community can do anything about it. |
| **Accounts this is for** | **Everyone**, **Accounts that existed when it was published**, or **Accounts made since it was published** | It's about a transition. The second is for a change people lived through; the third is for a tip aimed at somebody just arriving. |
| **Publish at** | A date and time, in your timezone, or **Publish now** | You want it to go out later. Empty, it stays a draft that only announcement writers see. |
| **Stop showing at** | A date and time, or empty | It stops being true on a date. |
| **Show on page (optional)** | A path pattern | It explains a screen. The notice waits until somebody opens a matching page, rather than queueing at sign-in. |
| **Times to acknowledge** | 1 to 10 | Missing it would cost somebody real work. It comes back until they've dismissed it that many times. Keep it at 1 unless you mean it. |

The list shows each one as **Draft**, **Scheduled**, **Live** or **Expired**.

### Path patterns

A pattern starts with `/` and matches a page's path one part at a time:

| Pattern | Matches |
|---|---|
| `/c/*/settings` | Any community's settings page. `*` stands for one part of the path. |
| `/c/**` | Every page inside any community. `**` stands for the rest of the path, so nothing may follow it. |

A pattern with a space in it, or a `*` joined to other characters, is refused as you type, with the reason.

## What readers get

- The dialog appears the next time they use Initiative or, with a path pattern, when they open a matching page. When several are waiting, it says how many more.
- **Got it** dismisses it. It comes back only if you asked for more than one acknowledgement, and the dialog says so ("shows once more").
- A picture opens full size when selected.
- The first time somebody closes a notice, a line lands in their notifications, already read, that opens it again until the notice's **Stop showing at**. Read notifications clear themselves after 30 days.

## Editing, unpublishing and deleting

- **Editing** a live announcement changes it for everyone who hasn't dismissed it yet. People who already have don't see it again.
- **Back to draft** takes a published announcement out of circulation without losing it.
- **Deleting** removes it along with everyone's record of having read it. Delete and re-create the same notice and people who already dealt with it see it again, so edit the original.

!!! note "Announcements aren't translated"
    Sections are written once and shown as you wrote them, whatever language the reader uses. Only the dialog's own buttons follow their language. Write plainly, and keep it short.
