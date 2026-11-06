---
icon: lucide/bell
---

# Notifications

Initiative can tell you when something wants your attention — a task landed on you, somebody mentioned you, an event is creeping up.

What you get told about, and where, is entirely yours to decide. Nothing is being pushed into your inbox on your behalf for your own good.

## The channels

| Channel | What it is |
|---|---|
| **Bell** | The in-app bell, and the notifications page behind it. |
| **Email** | Messages to your inbox. |
| **Mobile** | Push notifications on your phone (needs the app, and permission). |
| **Desktop** | Notifications from the [desktop app](../getting-started/install-the-app.md#the-desktop-app), whenever its window isn't the one in front. |

All of them are yours, row by row, with no minimum — the bell included. Three rows keep the bell whatever you set: **Waiting on you**, **Moderation** and **Your account**. Somebody's waiting on your decision, or somebody did something about you or your account. None of that is a thing to discover in March. Their other switches turn off like anything else.

## The bell, and the page behind it

The **bell** holds everything you haven't read. Not the last twenty — the lot. The number says how many; opening it says what.

Everywhere else you get a **dot**: on the community in the left rail, then the initiative, then the tool, then the project or file in that tool's list, then the task, event or page inside it. Follow the dots inward and you land on the thing, instead of opening five communities to work out which one was buzzing.

Open it and the comments you haven't read are picked out, with the page scrolled to the first. Opening it also reads everything about it — the dots clear and the bell counts down, without you going back to click the notification.

**See all**, at the foot of the bell, opens the full record — read and unread, grouped by day, filterable to unread, to mentions, or to one community. Anything in it can be marked read, marked unread again, or thrown away.

A read notification stays in the record for **30 days** after you read it, then clears itself out. Unread ones wait for you however long you take, including the whole of August.

Two surfaces, two jobs. The bell is what's left to deal with. The page is what happened.

Notifications arrive **as they happen** — a mention lands the moment it's written. Reading one clears it on your other tabs too, so you don't dismiss the same thing three times on three devices.

!!! note "Click one and it stays put"
    It dims instead of vanishing, so the list doesn't reshuffle itself while you're still reading. It clears out when you close the bell.

## Turning on mobile push

1. Install the mobile app and sign in.
2. In **My Settings → Notifications**, choose **Turn on** beside **Push notifications**.
3. Say yes when your phone asks.

If push shows as **Blocked**, that's your phone rather than us. Open your device settings, find Initiative, and let it talk to you. We can ask; your phone decides.

## What you hear about

**My Settings → Notifications** gives you a grid: one row each, with a **Bell**, **Email**, **Mobile** and **Desktop** switch. **Mobile** appears once your server sends to phones.

The first four rows are about what happens in your communities, sorted by how it involves you rather than by what kind of thing it was.

| Row | You hear about it when… |
|---|---|
| **Mentions and replies** | Somebody writes your name, replies to something you said, or reacts to your comment. |
| **Assigned to you** | You're given a task or invited to something, or something you're on changes, gets cancelled, or is about to start. |
| **Subscribed** | Somebody changes, comments on or reacts to something you [follow](your-space.md#subscribing). That includes everything you made. |
| **New in your communities** | A post goes up where you can see it, you're added to an initiative or a project, or your request to join one is answered. |
| **Waiting on you** | Somebody needs your decision — a join request, an access request. |
| **Moderation** | A community's moderators took something you wrote down, or warned you about it. |
| **Messages and connections** | Somebody messaged you, asked to connect, or accepted. You're told who and how many — never what a message says, because nothing outside your own devices could tell you that. |
| **Exports and imports** | Something you asked for has finished. |
| **Your account** | Something was done to your account by somebody else. |

Everything here is about something you can open. A comment on a project that isn't shared with you doesn't reach you, and neither does a mention there — so somebody who wants you in a thread shares it with you first.

**Mentions and replies** and **Subscribed** are separate on purpose. Somebody typing your name is a decision about you. Somebody tweaking the seventh task in a project you made is just how busy the project got. Turn the second down; keep the first.

If you answer [cases](../running-a-server/platform-roles.md#where-operations-work-lands) on your server, those reach you too, with no row to switch. Answering them is the job.

![Notification settings](../images/notifications/settings.png)

## Digests

The grid is things as they happen. **Digests** are the summaries: one message, on a schedule, each with its own switches, its own day and its own time.

| Digest | What's in it |
|---|---|
| **Overdue tasks** | Every task assigned to you that's past its due date, from every community, in one list. On until you say otherwise. |
| **Coming up** | The tasks due and the events starting before the next one. Off until you ask for it. Weekly on a Monday at 08:00 is a decent way to meet the week before it meets you. |

Each goes **every day** or **every week**, at the time you pick, by email, to your phone, or both. Everything in one is already in your bell, so a digest is the list rather than more news. An empty one doesn't arrive: no overdue tasks, no overdue email.

### Gathered email

Everything in the grid can reach your inbox the moment it happens, or wait and come as one message. That's **Email arrives**.

| Email arrives | What lands in your inbox |
|---|---|
| **Right away** | One message per thing, as it happens. The default. |
| **Once an hour** | On the hour, everything since the last one. |
| **Once a day** | One message, at a time you pick. |
| **Once a week** | One message on a day you pick. |

The digests above keep their own times, whatever you pick here.

Anything held comes as a **single** message, grouped by community and then by what it was:

```
Foundry
  Mentions and replies
    Alice mentioned you in a comment on Fix the login redirect
  Subscribed
    Alice and 2 others — 5 comments on Fix the login redirect
Acme
  Assigned to you
    Dana invited you to Sprint review (Tue 10:00)
```

Two things soften the edges of that:

- **Things addressed to you skip the queue.** A mention, a reply, a task landing on you, an invitation, a direct message — those go out straight away whatever you've chosen. The ambient stuff waits. Turn off **Send things addressed to me right away** if you'd rather they waited too.
- **Anything you've already read is dropped.** If you saw it in the bell before the email went, it doesn't go. The digest is what's still waiting, not a recap of your afternoon.

## Other timings worth knowing

- **Everything on one thing** arrives as **one line**, however much there is. Twenty edits and comments on a task you follow is one notification naming who and how many — not twenty. Once you've read it, the next one starts a fresh line, so new activity is still news.
- **Changes** gather for about a minute before they're told, so somebody fixing a typo four times in a row is one change.
- **A plug-in's changes** — an automation closing a task, a calendar moving an event — reach the people on the thing, under **Assigned to you**, with the plug-in named. They don't reach everyone following it, so a busy automation doesn't fill **Subscribed**.
- **Mentions in a text document** arrive as one line too. Somebody tidying a page that names you in four places tells you once, until you've read it.
- **Task assignments** arrive as one summary once the dust has settled. Somebody assigning you ten things reaches you as one message rather than ten.
- **Reactions** work the same way, for the same reason: they arrive in flurries.
- **Event reminders** are set per event — at the start, or a chosen number of minutes, hours or days before.

!!! tip "Set your timezone. Genuinely."
    Digests, quiet hours, due dates and repeating-task maths all run on your timezone. Initiative guesses it from your browser at sign-up and is usually right.

    But if your daily email is arriving at 4am, you have not been cursed and nothing is broken. Check **My Settings → Preferences**.

## Do not disturb

Three ways to be left alone, all under **Do not disturb**: one for while you're here, one for every night, and one for the fortnight in Portugal.

### Don't interrupt me while I'm using Initiative

If you're sat here with Initiative open, the bell has already told you. So it doesn't also tap you on the shoulder: **mobile stays quiet, and email waits about ten minutes** to see whether you read it yourself. If you did, it never sends. If you wandered off, it does.

"Here" means *at the keyboard* — clicking, typing, scrolling. A tab left open on a second monitor since Tuesday doesn't count, and neither does a phone in a pocket.

Switch it off if you'd rather always be told.

The desktop app goes by its own window instead: it speaks up whenever that window isn't the one in front, so the next thing reaches you the moment you've gone to answer an email.

### Quiet hours

**Quiet hours** are for every night. Set a window — 22:00 to 07:00, say — and email, mobile and the desktop hold off inside it. The bell keeps collecting quietly; it was never going to wake you. When the window ends, everything held arrives as one message, the same digest shape as above. If nothing happened, nothing arrives.

### Pause notifications

Going away? **Pause notifications** stands email, mobile and the desktop down for the days you pick. Pick an end day and it starts now; pick a start day too and you can book the fortnight in Portugal before you leave, rather than remembering to do it at the airport. Both days are included.

While it's on, nothing reaches you — not a mention, not a direct message, not somebody typing your name in capitals. That's the point. A pause you have to keep checking isn't one.

The bell keeps collecting the whole time. When the pause ends you get **one email** with everything that happened, grouped the same way a digest is, minus anything you've since read. Mobile and the desktop get a count.

A digest that would have landed in the middle of a booked pause waits for the end of it too, so the days you marked off stay marked off.

!!! note "Password resets arrive regardless"
    Pausing covers notifications. It doesn't cover the email that turns up because you just clicked "forgot password" — that isn't a notification, it's an answer.

## Per community

Open a community under **Per community** and the first four rows are there again, one switch each. Switch **Subscribed** off for the parish council and you still hear when somebody names you there, while the vicar's fourteenth edit to the minutes passes you by.

**Mute** silences the whole community. That means everything, and somebody typing your name there is not an exception — a mute you have to keep checking isn't a mute.

Neither reaches **messages**, **connections** or **your account**, which were never a community's to silence.

## What your server and community decide

Your settings pick from what's on offer. Two people decide what that is — whoever runs the server, and each community for itself — and both can only ever make things quieter.

Either can keep notifications **inside the app**, rather than reaching phones, desktops or mailboxes. Either can also ask that what does travel says the kind of thing that happened — *"You were mentioned in a comment"* — and leaves the details for the app. Somewhere with a rule about what may appear on a lock screen has a reason for that.

The **bell always carries the whole thing**, wherever those two land. It stays inside the app, so it has everything.

A switch that looks decided for you was decided in one of those two places, and whoever runs the community will know which. Your account's own post — sign-in codes, address confirmations, password resets — arrives regardless: that's correspondence, not notification.

## Announcements

Notifications are about *your* work. An **announcement** is about the app itself: a version that changed something, a setting that moved, a maintenance window whoever runs the server wants you to know about.

They arrive as a dialog rather than quietly in the bell, because they're the kind of thing genuinely worth stopping you for. Some are a single card; a longer one becomes a few pages you step through with **Next**. **Got it** clears it and it doesn't come back — unless whoever wrote it asked for more than one acknowledgement, in which case the dialog says so up front.

Dismissed one at speed and immediately regretted it? Nothing is lost. The **info icon in the sidebar footer** opens **Past announcements**: everything you've been shown, newest first, read and unread marked, with a filter for the ones you haven't read. Pictures open full size on a click.

Run a server and want to write one? See [Announcements](../running-a-server/announcements.md).

## Related

- [Your space](your-space.md) — where your tasks and events gather.
- [Profile & preferences](../account/profile-and-preferences.md) — your timezone and everything else.
- [Announcements](../running-a-server/announcements.md) — writing them, for operators.
