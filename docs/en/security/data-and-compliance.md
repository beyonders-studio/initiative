---
icon: lucide/scale
---

# Data & compliance

This page is for whoever answers questions about data for their group: who owns it, where it's kept, what Initiative stores in a browser and about use, what leaves the server, and how people get their data out or erase it.

Everything here describes the software, which is the same whoever runs it. Whoever runs your server decides where it runs and sets some of the time limits below. See [Self-host or let us host it](../self-host-or-hosted.md).

## Who owns what

- **A community's content belongs to the community.** Its projects, tasks and files are the group's, and its admins act for the group: they decide who may see what, what gets exported, and what gets deleted.
- **Your account is yours.** Your profile, picture, preferences, handle and email addresses are yours across every community you're in, and yours to take with you or delete.
- **Your messages belong to the people in the conversation**, and to nobody else, including the community and whoever runs the server. See [Private messages](private-messages.md).

## Why the rules are what they are

Initiative treats privacy as a question of how the system is built. No platform role has standing access to a community's data. Reaching a community you don't belong to takes a grant that expires and leaves a record, and direct messages are encrypted so that no key to them exists outside the devices in the conversation.

Nothing in Initiative sends your content to an AI model on its own. An AI feature sends what you asked it about, when you ask, to the provider your community or server set up, and a community can turn AI off. See [AI features](../account/ai-features.md).

## Where your data lives

Everything Initiative stores sits in the deployment's PostgreSQL database and its file storage, which is a local disk or an S3-compatible store. Whoever runs the server chooses where those are, so data residency follows from where it's deployed. A self-hosted server in your office keeps your data in your office.

The exceptions are what Initiative keeps in a browser and what leaves the server, both below.

## How your data is protected

- **In transit:** HTTPS, served by the server or a proxy in front of it. When the deployment's address starts with `https`, Initiative marks its cookies secure and tells browsers to use HTTPS only.
- **At rest:** sensitive fields are encrypted in the database, among them email addresses, dates of birth, authenticator seeds, AI keys, single sign-on secrets and the email server password. Stored files are encrypted too where the server turns that on. The full list is in [How your data is kept separate](how-your-data-is-kept-separate.md#encryption).
- **End to end, for direct messages:** encrypted on the sending device and decrypted on the receiving ones. See [Private messages](private-messages.md).
- **Access control:** four gates and two overrides, enforced in the database. See [How your data is kept separate](how-your-data-is-kept-separate.md).

## What is kept in your browser

Initiative keeps a small amount on the device you use it from. What's essential is there to run what you asked for, and anything beyond that is yours to turn on or off.

### Essential

| What | Where | Why |
|---|---|---|
| Your sign-in session | A cookie, `session_token`, the page's own scripts can't read. It lasts 15 minutes by default and is renewed while you use the app. | Keeps you signed in between page loads. |
| A renewal token | A cookie, `refresh_token`, sent only to the sign-in routes. It lasts 30 days without use by default. | Renews your session without asking for your password again. |
| A single sign-on in progress | Two cookies, `oidc_flow` and `oidc_next`, that last 10 minutes. | Finishes a sign-in through your community's or server's provider. |
| Your preferences | Local storage | Theme, language, sidebar and list layouts. |
| What you had open, and unsent drafts | Local storage | So a reload doesn't lose your place or your typing. |
| Your answer to the cookie question | Local storage | So you're asked once. |
| Your direct messages and their keys | The browser's database (IndexedDB) | The only copy of your conversations on this device. See [Private messages](private-messages.md). |
| Content you've read, in the phone and desktop apps | The app's own database | So the app has something to show with no signal. Kept for a day, and erased when you sign out. |

Signing out clears the session cookies and, in a browser, your messages. Clearing the browser's site data clears the rest, and you land back on the sign-in page with default preferences.

### Optional

The cookie question asks only about what the deployment uses, and Initiative has one optional category to ask about: **Analytics**. That's which pages get used, the errors people run into and how fast pages load, with the browser and device, grouped by a random ID for each visit and never by account.

Analytics runs only when three things are true: the server has set up browser measurement (`FARO_COLLECTOR_URL`), the server asks visitors the cookie question, and you said yes. Ignoring the question, closing it, or never being asked all leave it off.

Separately, a server that collects metrics (`METRICS_TOKEN`) counts each page opened by its route pattern, such as `/c/$communityId/…`. That count keeps nothing in the browser and records nothing about who opened the page, so the cookie question doesn't cover it.

### The cookie chooser

The cookie question is off by default, because most servers are a group's own, reached by people who were sent a link. A platform owner turns it on:

1. Open the user menu and select **Platform Settings**.
2. Select the **Branding** tab.
3. Under **Cookie choices**, turn on **Ask arriving visitors about cookies**.

Where the server uses Analytics, the chooser shows **Reject optional** and **Accept all** side by side at the same size, so either is one click, and **Choose** opens a switch for each category. Where the server uses nothing optional, it says what's kept and offers **Got it**. The apps don't show it.

To change your answer, select **Cookies** in the landing page's footer, or go to **My Settings → Privacy** and select **Change** under **Cookies**. The settings entry appears in a browser, while the server asks the question and uses Analytics.

Your answer is kept in the browser you gave it in, and decides what that browser loads. Answered before you sign in, it stays in that browser until you do. Once you're signed in it's saved to your account too, so a browser or device that hasn't asked you takes your existing answer, and changing your mind on one device reaches the others. Your account keeps only the categories you allowed, the date, and which version of the question you answered. When a release of Initiative changes what the categories cover, you're asked again.

### Other sites a page contacts

| What | From | When |
|---|---|---|
| A sign-up spam check (hCaptcha, Cloudflare Turnstile or Google reCAPTCHA) | The vendor the server chose | On the forms that create an account or email a sign-in code, and only where the server set one up. The vendor's script sets a cookie of its own, under its terms. |
| The spell-check dictionary | `cdn.jsdelivr.net` | When you use spell-check in the editor. |
| Help search | The Initiative help center | When you search the help. |
| Whiteboard fonts | `esm.sh` | When a whiteboard opens. |
| An embedded video, design or document | The site it comes from | Where somebody embedded one. That site may set cookies under its own terms. |
| The API reference page | `cdn.jsdelivr.net` | When somebody opens `/api/v1/docs`. |

The app's own fonts and scripts come from the deployment. The only other script a page of the app loads is the spam check above.

!!! info "If you host it yourself"
    The tables above describe Initiative. A reverse proxy, CDN or web application firewall you put in front of it may add cookies of its own. Those are yours to document if your obligations call for it.

## What Initiative keeps about use

Two records of how a community's content is used are kept inside that community's own schema.

| What | Kept for | Used for |
|---|---|---|
| **Personal items.** One row per person per item: their latest open (when, and whether it came from search or the activity feed), whether they bookmarked it, subscribed or unsubscribed, a task reminder, and where they put a project in their own list. | Every open is kept 7 days. After that, an open of a project, file or other tool stays while it's among the person's recent items (20 unless they change **Recent items in tab bar**), and any other open is deleted. Bookmarks, subscriptions, reminders and places last until the person removes them. The whole row is deleted when the item is purged from the trash, when the person leaves the community, or when their account is erased. | Recent-item tabs, bookmarks, notifications, the order of their activity feed and project list, and, from opens, the engagement levels below. Each person sees only their own. |
| **Engagement levels.** A rough level for each item that at least three different people opened or changed in the last 7 days. No person and no count. | Worked out again every hour, so an item drops out once fewer than three people have engaged with it in the past week. | Ordering search, the command palette and pickers. Shown to nobody, and read only beside items the reader can already open. |

The levels come from the opens above and from the change log Initiative keeps for 7 days. No decision is made about a person. Anyone can stop their own activity counting with **Count my activity toward search ranking**, under **My Settings → Privacy**, and it stops counting from the next hourly update. A community with its own security standard can turn the levels off, and whoever runs the server can turn them off for every community. Either way, they're deleted at the next hourly pass. See [Ranking search by engagement](community-security.md#ranking-search-by-engagement).

## What leaves the server

Initiative sends content off the server only in these cases:

| What | Where it goes | What it carries |
|---|---|---|
| An AI feature someone uses | The AI provider the community or server set up | What they asked it about. A community can turn AI off with **AI features**. |
| Email notifications | The deployment's email server | The notification's text, which names the person and the item, unless notification details are hidden. |
| Push notifications | Apple or Google, through the project's push relay, except Android pushes on a server with its own Firebase project | The notification's title and text, as above. See [Push notifications](../running-a-server/push-notifications.md). |
| Webhooks | Addresses a community set up | Which item changed and the names of the fields that changed, by ID. No content. |
| Plug-in services | The plug-in's vendor | What the community allowed the plug-in to reach when it added it. See [Plug-ins & marketplace](../guides/plugins-and-marketplace.md). |
| Feedback | The Initiative team | What a person writes and chooses to send. Whoever runs the server can turn this off with **Let people send feedback to the Initiative team**, under **Platform Settings → Intake**. |

The server also contacts outside services that carry none of your content:

- **The password breach check** sends the first 5 characters of a new password's SHA-1 hash, while that check is on.
- **The plug-in registry** check downloads the signed list of plug-ins every 15 minutes, while the server follows the registry.
- **The update check** asks GitHub for the project's latest release, at most every 6 hours.
- **Sign-in providers and the spam check** are asked to confirm a sign-in or sign-up they took part in.

The breach check and the registry are on by default, and whoever runs the server can turn either off. See [Configuration](../running-a-server/configuration.md).

## Your data rights

### Getting your data out

- **Export any tool**, such as a project, file, wiki or calendar, to a portable file you can keep or import elsewhere, from its settings' **Advanced** tab. Exporting belongs to whoever can delete the thing: its owner, a community admin, or somebody with full access in its initiative. An initiative with **Block exports, and copies and moves to other initiatives** turned on exports none of its items.
- **Export a whole initiative** from its settings, and a whole community with **Export this community**, which only its superadmin can use. Each export holds what the person exporting can see. A community can export everything once every 48 hours, unless the server changes that.
- **Export spreadsheets** as CSV, Excel (XLSX) or JSON, projects and counter groups as CSV or XLSX, and contacts as CSV.
- **Export calendar events** as standard `.ics` files.
- **Export a member list**: community admins with **Export all as CSV** in **Users**, and platform moderators and above for every account on the server.

### Removing data

- **Anything deleted in a community** goes to its **Trash** first, and can be restored there until it's purged. Community admins choose how long that is: 90 days by default, anything from 1 to 3,650 days, or never. See [Working with communities](../guides/communities.md).
- **Deactivating your account** stops you signing in and removes you from every community you belong to, while your name, email and content stay. Whoever runs the server can reactivate it.
- **Deleting your account** hides it from everybody at once and erases it when the server's window ends. Signing back in before then cancels the deletion. Once it's erased, your name, email and picture are gone, your projects pass to other people, and what you wrote stays, shown as a deleted user. See [Profile & preferences](../account/profile-and-preferences.md).
- **A platform operator or owner** can also delete an account for good at once, skipping the window. It can't be undone. What the person wrote stays, with no owner.
- **A deleted community** disappears at once and is destroyed when the server's window ends. A platform operator can restore it before then.

The server sets both windows under **Platform Settings → Community**: **Keep accounts for (days)**, 30 by default, and **Keep communities for (days)**, 90 by default. Leaving either empty means **Never erase** or **Never destroy**, for a deployment required to keep records. See [Configuration](../running-a-server/configuration.md#how-long-deleted-things-are-kept).

**A plug-in knows people by names of its own.** Each plug-in in each community is given a random name for the community and for each member, never their account or email. Two plug-ins are given unrelated names for the same person. The names are kept while a plug-in is removed, so adding it back recognizes the same people. They're forgotten when the community removes the plug-in and erases its data, when the community is destroyed (each plug-in is asked to erase what it holds first), and when the person's account is erased.

Together, the export and removal tools cover the two requests privacy laws ask for most often: a copy of the data held about somebody, and erasing their personal information.

### Accountability

Initiative records an audit entry for actions that change who can reach what, how the deployment is configured, or where data goes. Each entry is one JSON line on the server's standard output, under the `audit` logger. It's kept wherever the deployment sends its logs, for as long as those are kept.

Entries name accounts and communities by ID, never by name or email address, and never contain a password, a key or the text of what somebody wrote. Every entry carries an ID for the request it came from. Entries about signing in and about privileged access also carry the network address and the browser or app the request came from.

What's recorded:

- **Signing in.** Sign-ins and failed attempts, signing out, password and two-factor changes, passkeys, account locks, and sessions ended.
- **Privileged access.** A break-glass grant, or an access request approved: who, which community, the level, and the case it's for. While the grant is live, every request made under it is recorded with the route, the method, the response and the grant. Editing a file or wiki page over a live connection is recorded the first time it happens in a session.
- **Membership and roles.** Joining or leaving a community or an initiative, role changes in either, custom roles, guests, ownership transfers, invitations issued and withdrawn, and every change to how an item is shared.
- **Platform roles and moderation.** Changes to someone's platform role, suspensions, held content, moderation removals, reports and the evidence opened on them, and age answers reset.
- **Configuration.** Sign-in providers and group rules, a community's sign-in requirement and security settings, email, storage and AI settings, plug-in services, plug-ins installed and what they were allowed, and rotating the server's secret key.
- **Signatures.** Each time somebody signs a signature field: who, and which item and field.
- **Accounts and data.** Accounts created, deactivated, scheduled for deletion, restored, anonymized or deleted. Communities created, deleted, restored or exported. Initiatives exported or deleted. Member lists exported, permanent deletion from the trash, API keys, webhooks, and each time content is sent to an AI provider.

Privileged access is also told to the community. Access for a support case is always emailed to the community's superadmins when it starts. For a security or moderation case, the staff member asking chooses whether they're emailed when it starts, once it has ended, or not at all. The email names the level, the kind of case and the times, and leaves out the stated reason.

### Age

While whoever runs the server has **Check members' age** turned on (it is by default, under **Platform Settings → Community**), every account is asked its date of birth once: at sign-up, or the next time it signs in without one.

| Age limit | What it governs |
|---|---|
| The minimum for an account | 13 in most countries, and higher where local law sets an older age of digital consent, up to 16. Sign-up refuses anybody younger. An existing account that answers below it is closed and scheduled for erasure, and signing in doesn't cancel that. Platform support staff and above can clear it. |
| 16 | Joining a community listed in the community directory, which anybody signed in can find, and sending direct messages. |
| A plug-in's minimum | Set by each plug-in and may differ by country. Somebody younger can't open or use that plug-in, though their community can still install it. |

**Where you are comes from your connection.** If the server sits behind a proxy that reports a visitor's country (`CLIENT_COUNTRY_HEADER`), Initiative reads it for that request and doesn't store it. Where the country isn't known, the highest age that applies anywhere is used.

**The date is kept encrypted.** It's stored apart from the rest of the account, read only to check an age limit, never sent back in any response (to you included), and never logged. It isn't kept when the answer is below the account minimum, and it's deleted with the account.

**An answer under 16** is recorded. It closes the directory's **Join** button and messaging, and takes nothing else away. Platform support staff and above can reset the question, which is the way back from a mistyped year, and the reset is recorded in the audit log.

A community that isn't listed sets no age limit, however somebody joins it. An account that hasn't answered keeps every community it belongs to and everything in them. A community is refused a listing while it holds anybody who answered under 16.

## What could be handed over

If somebody with legal authority asks whoever runs a server for its data, this is what exists:

| Asked for | What exists |
|---|---|
| Projects, tasks, files and other community content | All of it, in the database and file storage, readable by whoever runs the server. |
| The content of direct messages | Only encrypted text still waiting to be collected, with no key to read it. Collected messages aren't on the server at all. |
| Who messages whom | Each conversation's members, when it started, and when each member joined and accepted it. Each device and when it last collected messages. The sender and count of unread message alerts. |
| Account details | Handle, email addresses, when the account was created and last active, and its settings. Signed-in sessions, with the network address, browser or app, and device name, kept until 30 days after each session ends. Linked sign-in accounts, passkeys and devices registered for notifications. |
| The audit log | Wherever the server keeps its logs. |

A self-hosted server's data is between whoever runs it and whoever is asking. Nobody else holds a copy.

## Compliance

!!! info "Initiative supplies controls. Compliance belongs to an organization."
    A certification or a legal status attaches to an organization and how it operates, never to software alone. Initiative provides the technical controls below. Whoever runs the server, and the group using it, provides the rest.

**What Initiative provides:**

- **Separation between communities**, enforced in the database. See [How your data is kept separate](how-your-data-is-kept-separate.md).
- **Least-privilege database logins**, and no standing bypass for any role a person's request uses.
- **Encryption** of sensitive fields at rest, optional encryption of stored files, secure cookies and HTTPS-only headers when served over HTTPS, and end-to-end encryption for direct messages.
- **Access control** at four levels: community, initiative, role, and each item's sharing.
- **Time-limited, recorded staff access**, never a permanent way in.
- **Export and erasure tools** for requests about personal data.
- **Retention you set** for trash, deleted accounts and deleted communities.
- **Single sign-on (OpenID Connect)**, so identity, password rules and removing accounts can stay with your existing identity provider.
- **An audit log** of access, configuration and data changes.

**What belongs to whoever runs the server:**

- **Data protection law (such as the GDPR or the CCPA):** the organization using Initiative decides what it collects, why it's allowed to, and how it answers its own members' requests. Initiative supplies the technical side: export, erasure, access control, and residency by choice of host.
- **Formal certifications (such as SOC 2 or ISO 27001) and regulated data (such as HIPAA):** earned by the hosting and the processes around it: key management, backups, monitoring, physical security and staff access.
- **Backups, disaster recovery, monitoring and updates.** See the [server guide](../running-a-server/index.md).

!!! warning "No legal advice"
    This page describes capabilities, not a legal guarantee. For regulated data, review your obligations with a qualified professional and document how your deployment meets them.

## A checklist for whoever runs the server

If compliance matters to your group:

- [ ] Serve Initiative over **HTTPS**, and set `APP_URL` to its `https` address.
- [ ] Set a **strong, unique `SECRET_KEY`**, and back it up with your other secrets. The encrypted fields, and stored files under `STORAGE_ENCRYPTION=local`, can't be read without it.
- [ ] Take **regular, tested backups** of the database and uploaded files.
- [ ] Keep Initiative **updated** to the latest release, which is the one that gets security fixes.
- [ ] Set **Keep accounts for (days)** and **Keep communities for (days)** to match your retention policy, and ask community admins to set their trash retention.
- [ ] Prefer **single sign-on**, so accounts are managed in one place.
- [ ] Send the server's logs somewhere that keeps the audit entries as long as you need them.
- [ ] Review who holds the **operator** and **owner** platform roles, who holds each community's admin and superadmin seats, and who can break glass.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md): the technical isolation model.
- [Private messages](private-messages.md): what end-to-end encryption covers.
- [Backups & updates](../running-a-server/backups-and-updates.md): your operational responsibilities if you host it yourself.
- [Reporting a problem](reporting-a-problem.md): where to report a security problem.
