---
icon: lucide/inbox
---

# The operations community

Somebody reports a comment, somebody can't get into their account, and somebody else notices the same address has failed to sign in a few hundred times since lunch. Each of those opens a case, and the cases land in one community of your choosing: the operations community. It's an ordinary community in every way, and its members work the cases like any other tasks, on boards and in lists they already know.

Everything here is on **Settings → Platform → Intake**, which only an [owner](platform-roles.md) can open.

## Set it up

1. Open **Settings → Platform → Intake**.
2. Under **Operations community**, choose the **Community**. It has to be active.
3. Under each kind of case (**Security**, **Moderation** and **Support**), choose an **Initiative** and select **Set this up for me**, or choose a project under **Or use a project you already have**.
4. Optionally choose where cases start (**New cases start in**) and which task type they are (**New cases are**).
5. Optionally choose the status that means **Waiting on the requester**, and the one **When they answer, move to**. **Set this up for me** picks both.
6. Under **Who to contact**, fill in the addresses (see [below](#who-to-contact)) and select **Save contacts**.

**Set this up for me** makes a ready-made project with its own statuses and fields, which you can restructure however you like afterwards. Give security and moderation an initiative each, so only the people working those cases can read them. The page warns you when two kinds share an initiative.

Each kind has its own **Receiving new cases** switch to pause it, and **Stop routing this stream** to unbind it. Its project and every case in it stay either way, and pointing it back at the same project picks up where it left off. Pointing a kind at a different project starts fresh there, and anything still open stays where it is.

Setting the community back to none stops every kind at once and leaves everything where it is, so choosing the same community again restores the setup. Choosing a different community starts fresh there. The community you leave keeps its cases as ordinary tasks, but their attachments are deleted, and requesters stop seeing those cases under **My Tickets**.

A plug-in set to **Only the operations community** under [plug-in services](plugins.md) follows whichever community you choose here.

## The kinds of case

| | Security | Moderation | Support |
|---|---|---|---|
| Opened by | The server's own [security rules](#security-cases-open-themselves), a person's report, or by hand | A person's report, or by hand | A person's help request, a community naming its sign-in claim values, or by hand |
| Talking with whoever filed it | Yes | No, except a suspension appeal | Yes |
| Filings per account | 5 a day | 30 an hour | 10 an hour |
| Open at once per account | 10 | No limit (1 appeal) | 5 |
| Attachments | Up to 5 files of 10 MiB each: PNG, JPEG, GIF, WebP, PDF or plain text | The same, and none on an appeal | The same |
| Attachments kept after the case closes | 365 days | 90 days | 90 days |
| Can be named on an [access grant](platform-roles.md#grants-and-their-cases) | Yes | Yes | Yes |

Everybody who can read a case hears when it opens: the people its project is shared with, and the operations community's admins. They also hear when a requester answers a case nobody has taken yet. Each person can turn these off under **Cases** in their own notification settings.

**Take this case**, on the case's panel, assigns you beside whoever already has it and moves a case still waiting to be picked up into progress. From then on, the requester's answers go to whoever took it.

### Answering the person who filed it

People follow the cases they filed under **My Tickets**, where each one reads **Received**, **In progress**, **Waiting on you** or **Closed**. A case shows **Waiting on you** while it sits in the status you chose for **Waiting on the requester**, and their answer moves it to the status you chose for **When they answer, move to**. With neither chosen, they never see **Waiting on you**.

Answer them from the panel on the case, which is kept apart from its comments, so the team's own discussion stays the team's. They see your replies as coming from the team rather than from you by name.

## Help requests

People ask for help behind **Ask for help**, which searches this help center first and offers the support form when the answer isn't there.

- **About their own account** (signing in, or anything else): anybody signed in can ask from anywhere, inside a community or not, once **Support** is set up. A person locked out of something has no community to ask from.
- **About a community**, or for a copy of its data or its deletion: only in a community whose **Help requests** switch is on. It starts off, and you turn it on from that community's [**Manage** sheet](platform-roles.md#what-you-decide-per-community). Off, **Ask for help** in that community opens the FAQ instead.

With **Support** not set up, the panel gives the support address from [Who to contact](#who-to-contact), or no address at all if there isn't one.

Each support case carries the topic its asker chose, shown on the case.

## Moderation cases and appeals

A report about content or conduct opens a moderation case. A report about one thing carries a `subject_link` that opens it in its community: the task, page or post, or the thread a comment is in, scrolled to the comment. It opens only for somebody who can read it there, so staff take a [Moderate grant](platform-roles.md#what-a-grant-can-say) on the community first. A reported picture has no page of its own and gets no link.

A suspended account can appeal from its time-out screen, while **Moderation** is set up. The appeal is a moderation case with the topic **Suspension appeal**, and unlike a report it's a conversation: reply from the case as you would on support. An appeal is words only, with no attachments, and one account has one appeal open at a time.

## Security cases open themselves

The server watches what its audit log records, and a run of something that looks wrong opens a security case. These are the rules:

- Many failed sign-ins from one address
- An account's sign-in was locked
- A spent session token was used again
- Many wrong second-factor codes for one account
- An operator broke glass on a community
- An account was made an operator or owner
- Staff cleared an account's second factor
- The user list was exported
- A one-time token or assertion was presented again
- Many cross-site request refusals from one address
- One address kept hitting the rate limit
- Many refused captchas from one address
- An API key kept reaching past what it may do

A rule that keeps tripping adds a note to its open case rather than opening another. The thresholds and windows are fixed in code, not in settings. Each case points at a `security.threshold_crossed` line in the [audit log](configuration.md#logs), which names what was counted.

People report security problems from the app too, with **Report a security problem**, into the same project. Every email about a change to how an account signs in carries a "This wasn't me" link as well, which ends every session on the account and files a security case about it.

`/.well-known/security.txt` tells people outside where to report. It names your security address, or the general one, and the in-app form while **Security** is set up. It says it holds for 180 days from when it's read. With no address at all, it answers 404.

A problem with the Initiative software itself, rather than your server, belongs with the project: forward it, and put the project's reference in the case's `tracker_key`.

## Held content

A community's moderators (its admins, or anybody with Full access in the content's initiative) can **Hold for the platform** something under a legal request to keep it, or that may be illegal. A platform moderator under a Moderate grant can hold reported content directly from a case, with **Hold the reported content**.

Held content disappears for everyone in that community, its admins and the person who held it included, and nobody there can change or delete it. What's held includes everything inside it: a project's tasks and their comments, a wiki's pages, and the uploads they show. A comment is held alone, and its replies stay under a placeholder. The community can't be deleted for good while anything in it is held, and the author is never told.

Each hold opens a moderation case in the operations community, or lands on the case a platform moderator placed it from. The case shows its **Holds** to anyone with a Moderate grant on that community: why it was held, which law, the note left with it, and three ways to release it.

| Release | What happens |
|---|---|
| **Restore** | It's back exactly as it was. |
| **Remove** | It's taken down through the community's moderation log. A comment becomes a line saying it was removed, and anything else goes to the community's trash. |
| **Purge** | It's destroyed for good, with everything held with it. This asks you to confirm. |

A hold never expires. Every 30 days it stays in place, its case is reminded.

## Who to contact

Whenever Initiative tells somebody to get in touch, it names an address. You set them under **Settings → Platform → Intake → Who to contact**: a **General contact**, then one for each kind of case.

| When somebody sees | It names |
|---|---|
| Their account's time-out screen | Moderation |
| A suspended community | Moderation |
| A report that had nowhere to go, because **Moderation** isn't set up | Moderation |
| A community on hold | Support |
| An email telling a community that staff have access | Support |
| **Ask for help**, where **Support** isn't set up | Support |
| `security.txt`, and the "This wasn't me" page | Security |

A kind left blank uses the general address. It never borrows another kind's, so a moderation question doesn't turn up in the support inbox wondering why it's there. With neither set, the notice says to contact whoever runs this server, which is true but not much help to somebody who doesn't know who that is.

## Feedback to the Initiative team

**Send feedback** goes to the team that makes Initiative, not to you. The app opens the feedback page on Initiative Cloud in the browser, and the person signs in there, so nothing passes through your server. Ideas about the software reach the people who can build them, and your inbox stays yours.

It's on until you switch off **Let people send feedback to the Initiative team**, under **Settings → Platform → Intake**. Off, nobody on your server is offered **Send feedback**, which suits a server that shouldn't reach the internet at all.

## Related

- [Platform roles](platform-roles.md), for the staff who work cases and the grants they take.
- [Configuration](configuration.md#logs), for the audit log.
- [Notifications](../guides/notifications.md), for how case notifications reach people.
