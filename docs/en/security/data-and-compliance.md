---
icon: lucide/scale
---

# Data & compliance

This page explains who owns your data, where it lives, the rights you have over it, and — honestly — what compliance posture you can and can't expect. It's written for the people who have to answer these questions for their organization, but the first part is for everyone.

## Two ways to run Initiative

One product, two ways to get it, and the difference is mostly about who does the operational work:

- **You host it yourself.** Open source, running on hardware your group controls or a host your group picked. Everything below applies — you just hold the machine too.
- **We host it for you** *(coming soon)*. A paid service: you sign up and start, and keeping it running, backed up and current is ours.

Same software, same protections — nothing is held back from the version you run yourself. Where a section below depends on which you picked, it says so. See [Self-host or let us host it](../self-host-or-hosted.md).

## Who owns what

The rule is a simple one: **communities own community data, and people own their own.** In practice that means:

- **A community's content belongs to the community.** Its projects, tasks and files are the group's, and its admins act for the group — they decide who may see what, what gets exported, and what gets deleted. Writing a task doesn't make it privately yours any more than minuting a meeting makes the minutes yours.
- **Your account is yours.** Your profile, your picture, your preferences, your handle and email address — yours across every community you're in, and yours to take with you or delete.
- **Your messages are yours and the other person's**, and nobody else's. Not the community's, not an admin's, not ours. See [Private messages](private-messages.md).

None of it is ours. We don't sell it, we don't mine it, and we don't train on it — there's no path in the architecture for us to. (The one time your content deliberately leaves your server is when somebody presses an AI **Generate** button, and then it's the provider's terms that apply. See [AI features](../account/ai-features.md#the-privacy-bit-which-is-genuinely-worth-reading).)

If you host Initiative yourself, all of it sits in *your* database and *your* file storage, and backing it up is your job too. See [Backups & updates](../running-a-server/backups-and-updates.md).

If we host it, we hold it **on behalf of the people it belongs to**, and the tools stay in their hands: export it whenever you like, delete it whenever you like, take it elsewhere. The export formats below are ordinary files, not something only we can open.

## Why the rules are what they are

Some of the choices below look severe until you know where they came from.

We treat privacy as an architecture problem rather than a policy one. A policy lasts exactly as long as whoever owns the company next; a system with no path to your content doesn't depend on anybody's good intentions. Hence no standing access to a community's data for anybody running the platform, cross-community access only through a time-bound grant that leaves a record, and direct messages encrypted so thoroughly that no key to them exists outside the two devices talking.

The practical upshot: **we can't feed your work to a model, because there's no pipe to put it in.** The AI features that do exist are ones you point at your own content deliberately, with a key supplied by your community or whoever runs your server, and they send only what you asked. See [AI features](../account/ai-features.md).

The longer version of why is on the [home page](../index.md#why-we-built-this).

## Where your data lives (data residency)

If you host Initiative yourself, your data lives wherever your server runs. If that's a computer in your office, your data is in your office; if it's a cloud server in a particular country, your data is in that country. **You choose** — which makes meeting data-residency requirements a matter of where you deploy, not something to negotiate with a vendor.

If we host it, your data lives where our service runs. For a group with a residency requirement it can't meet, self-hosting is always there — it's the same software, and there is no feature held back from it.

## How your data is protected

- **In transit:** traffic between browsers and the server is encrypted over HTTPS.
- **At rest:** the most sensitive stored fields — saved AI keys, single-sign-on secrets, email-server passwords, and email addresses — are encrypted in the database.
- **End-to-end, for direct messages:** private messages are encrypted on the sending device and decrypted on the receiving one. Nobody in between can read them, including us and including whoever runs the server they passed through. See [Private messages](private-messages.md).
- **Access control:** everything else is gated by the [six-layer model](how-your-data-is-kept-separate.md) and enforced in the database.

## What is kept in your browser

Initiative stores a small amount on the device you use it from. What's essential is there to run what you asked for; anything beyond that is yours to switch on or off.

### Essential

Always present, because there is no version of Initiative without it.

| What | Where | Why |
|---|---|---|
| Your sign-in session | A cookie the page's own scripts can't read | Keeps you signed in between page loads. |
| A renewal token | A cookie sent only to the sign-in routes | Renews the session without asking for your password again. |
| Your theme, language and layout | Local storage | Your preferences, kept where you set them. |
| What you had open, and unsent drafts | Local storage | So a reload doesn't lose your place or your typing. |
| Recently read pages, on the mobile app | The device's own storage | So the app has something to show with no signal. |

Signing out clears the session and renewal cookies. Clearing your browser's site data clears the rest; you'll land back on the sign-in page with default preferences.

### Optional

Initiative knows two: **analytics** — which pages get used, the errors people run into and how fast pages load, with the browser and device, grouped by a random id for each visit and never by account — and **marketing**, which link brought you here and reaching you about Initiative elsewhere.

Separately, a deployment that collects server metrics counts pages opened by their pattern (`/c/$communityId/…`). That count keeps nothing in the browser and records nothing about who opened the page, so it needs no switch.

**You are only asked about the ones your deployment actually uses.** Both ship switched off, so a server run by a group for itself uses neither and never asks about either. Where a deployment has configured one, it gets a switch, and that switch starts off. Ignoring the question, closing the chooser, or never being asked all leave everything optional off.

### The cookie chooser

A deployment can put the question to arriving visitors. It is **off by default** — most deployments are a group's own server, reached by people who were sent a link — and a platform owner turns it on under **Settings › Platform › Branding**.

Where it is on and the deployment uses something optional, **Reject optional** and **Accept all** sit side by side at the same size, and either is one click; **Choose** opens a switch per category. Where the deployment uses nothing optional, there is nothing to decide, so it says what is kept and offers a single acknowledgement.

You can change your mind at any time: the landing page's footer reopens the chooser, and so does **Cookies** under **User settings › Privacy**.

Your answer is kept in the browser you gave it in, which is what decides what that browser loads. Answered before you sign in, it stays there and goes nowhere — somebody reading the landing page has no account to attach it to.

Once you're signed in it also belongs to your **account**, so a browser or device that has never asked you takes your existing answer instead of asking again, and changing your mind on one device reaches the others. Where the two disagree, an answer you have just given wins over one carried from elsewhere. Your account keeps only the categories you allowed, the date, and which version of the question it answered.

If the categories change, you're asked again.

### The one outside company

Where whoever runs the server has configured a **sign-up spam check** — hCaptcha, Cloudflare Turnstile or Google reCAPTCHA — that vendor's script runs on the sign-up form, and sets a cookie of its own under their terms. It loads on that form and nowhere else, and only on a deployment that configured one. The chooser names the vendor where it applies.

Fonts are served from the deployment's own server, and no page loads a script from anywhere but the vendor above.

!!! info "If you host it yourself"
    The tables above describe Initiative. A reverse proxy, CDN or web application firewall you put in front of it may add cookies of its own — that's yours to document if your obligations call for it.

## What Initiative keeps about use

Two records of how a community's content is used are kept inside that community's own data, and neither leaves the server.

| What | Kept for | Used for |
|---|---|---|
| **Personal items.** What each person keeps about each item in a community, one row per person per item: their latest open (when it was, and whether it came from search or the activity feed), whether they bookmarked or subscribed to it, and where they put a project in their own list. | An open is kept at least 7 days, then only while the item is among the person's recent tabs. A bookmark, a subscription and a place last until the person removes them. The whole row is deleted when the item is purged from the trash, when they leave the community, or when they delete their account. | The recent-items tabs, Bookmarks, the order of their activity feed and project list, and, from opens only, the engagement levels below. Each person sees only their own. |
| **Engagement levels.** A rough level for each item that at least three different people opened or changed in the last 7 days. No person, no count. | Worked out again every hour, so an item drops out once fewer than three people have engaged with it within the week. | Ordering search, the command palette and pickers. Shown to nobody, and read only beside items the reader can already open. |

The levels are worked out from the opens recorded above and from the change log Initiative already keeps for 7 days. No decision is made about a person. Anyone can stop their own opens and changes counting under **My Settings → Privacy**; they stop counting from the next hourly update. A community holding its own security standard can turn the levels off, and whoever runs the server can turn them off for every community. Either way they are deleted within the hour. See [Ranking search by engagement](community-security.md#ranking-search-by-engagement).

## Your data rights

### Getting your data out

Initiative is built to avoid locking your information in:

- **Export any tool** — a project, a file, a wiki, a calendar and the rest — to a portable file you can keep or re-import elsewhere, from its **Settings → Advanced**. Exporting belongs to whoever can delete the thing: its owner, and anyone who can see everything in its initiative.
- **Export spreadsheets** as CSV or Excel (XLSX).
- **Export calendar events** as standard `.ics` files.
- Platform operators can **export the user list** as CSV.

### Removing data

- **Anything you delete** goes to the **Trash** first, where it can be restored until the retention period passes — then it's permanently removed. Community admins set how long that is (see [Working with communities](../guides/communities.md#trash-and-retention)).
- **Your account** can be **deactivated** (you can't sign in, but your content stays) or **deleted**. Deleting offers a choice: *anonymize* (your personal details are removed and your past contributions show as "Deleted user") or, for platform operators, *hard delete* (everything is removed). See [Profile & preferences](../account/profile-and-preferences.md).
- **Deletion takes effect immediately and completes after a retention window.** A deleted account disappears for everyone else at once and is erased when the window ends; signing back in before then cancels the deletion. A deleted community behaves the same way and can be restored by a platform operator until its window ends. The deployment sets both windows — 30 days for accounts and 90 days for communities unless changed, or no automatic erasure at all where a deployment is required to retain records. See [How long deleted things are kept](../running-a-server/configuration.md#how-long-deleted-things-are-kept).

- **A plug-in knows people by a name of its own.** Each plug-in in a community is given a random name for the community and for each member, never their account or email, and two plug-ins are given unrelated names for the same person. The names are kept while the plug-in is removed, so adding it back recognises the same people. They are forgotten when the community removes the plug-in and erases its data, when the community is deleted for good (each plug-in is asked to erase what it holds first), and when the person's account is erased.

Together, the **export** tools above and these **removal** tools cover the two requests privacy laws ask for most often: handing someone a copy of the data held about them (a *right to access* request), and erasing their personal information (a *right to erasure* request).

Where an erasure has to complete sooner than the retention window allows, a platform operator's **hard delete** removes the account and everything cascading from it immediately, and cannot be reversed.

### Accountability

Actions that change who can reach what, how the deployment is configured, or where data goes are **recorded** in an audit log. Every entry is written out as one line to the deployment's log platform, which is where it is kept, queried and retained. Entries name accounts by id rather than by name or email address, never contain a password or a key, and outlive the accounts and communities they name. Each entry also records the request it came from: an identifier for that request, the network address it arrived from, and the browser or app it was made with. What is recorded:

- **Privileged access.** When a platform operator or owner uses an emergency "break-glass" grant, or a time-bound access request is approved, the entry says who, which community, and why. While that access is live, **every request made under it is recorded individually** — the route, the method, the response, and the grant it was made under — so what was reached is on the record and not only that access was held. Access for a support case is also emailed to the community's superadmins when it starts; for a security or moderation case, the staff member asking chooses whether they are emailed when it starts, once it has ended, or not at all. The email names the level, the kind of case and the time, not the stated reason. Editing a file or a wiki page happens over a live connection rather than a request, and is recorded separately the first time it happens in a session.
- **Membership and roles.** Joining or leaving a community or an initiative, a change of role in either, invites issued and withdrawn, and every change to how a project, file or other item is shared.
- **Configuration.** Sign-in providers and claim rules, a community's sign-in requirement and settings, email, storage and AI settings, plug-in services and installed plug-ins.
- **Accounts and data.** Accounts created, deactivated, anonymized or deleted; communities created, deleted or exported; member lists exported; permanent deletion from the trash; API keys and webhooks; and each time content is sent to an AI provider.

### Age, and what we ask for

Every account is asked its date of birth once — at sign-up, or the first time it signs in after that without one. Communities listed in the community directory can be found by anyone signed in, so joining one requires you to be 16 or older. Plug-ins can also set a minimum age, which may differ by country: someone younger than a plug-in's minimum where they are cannot open or use it, though their community can still install it.

**The date is kept, encrypted.** It is stored apart from the rest of your account, encrypted at rest, and read only to check an age limit. No response ever sends it back — to you included — nothing logs it, and it is not sold or shared with anyone. Deleting your account deletes it. If you entered it wrongly, whoever runs the server can reset the question so you can answer again.

**Where you are comes from your connection, not from you.** A plug-in's minimum age can depend on the country you are in. Where the server sits behind a provider that reports a visitor's country, that is read for the request and not stored. Where it cannot be told, the plug-in's highest minimum age applies.

The question belongs to the community rather than to the way in: every route into a listed one is covered, an invite included. A private community — one that has not listed itself — never asks, whoever brings somebody in, and no other part of Initiative asks. An account that has not answered keeps every community it already belongs to and everything in it.

A community that was private until now is refused a listing while it holds anybody who has answered under the minimum, since its members joined it under no such rule.

If you answer that you are not old enough, that answer is kept — again, the fact and not the date — and you are not asked again. It closes the directory's Join button; it takes nothing away. Somebody on the support tier or above can reset the question for you, which is the way back from a mistyped year. Resetting it is recorded in the audit log, like every other action one person takes on another's account.

Where every account on a deployment is known to belong to an adult, the platform owner can switch the question off entirely, under **Settings › Platform › Community**.

## What could be handed over

A question worth answering before you have to ask it: if somebody with legal authority demanded your group's data, what exists to give them?

**On a server you run**, the answer is between you and them — nobody else holds a copy to be asked for.

**On a server we run**, we answer lawful requests, and what we can produce is limited to what actually exists:

| Asked for | What exists |
|---|---|
| Projects, tasks, files | Held on your behalf, and readable. This is your working data. |
| The content of direct messages | **Nothing.** They are end-to-end encrypted; no key to them exists outside the devices in the conversation. |
| That two people have a conversation, and when | The fact and the timing. Encryption hides what was said, not that anyone spoke. |
| Account details | Handle, email address, and account timestamps. |

The messages row is not a policy we could revise under pressure — there is nothing stored that we are able to read. See [Private messages](private-messages.md).

## What compliance can you expect?

Here's the honest, useful answer.

!!! info "Initiative gives you the building blocks; your deployment determines your compliance."
    Initiative provides the technical features that support a strong compliance posture. A certification or a legal compliance status, though, always attaches to an **organization and its operations** — so part of the answer is ours and part of it is yours, and which part depends on who runs the server.

**What Initiative provides, either way:**

- **Strong tenant isolation** enforced in the database (see [How your data is kept separate](how-your-data-is-kept-separate.md)).
- **Least-privilege database roles** and no standing all-tenant bypass.
- **Encryption** of sensitive data at rest, HTTPS in transit, and end-to-end encryption for direct messages.
- **Granular access control** (community, initiative, role, and per-item sharing).
- **Audited, time-bound privileged access** instead of permanent back doors.
- **Data export and erasure** tools that support data-subject requests.
- **Configurable retention** for deleted content.
- **Single sign-on (OIDC)** so you can centralize identity, password policy, and account de-provisioning in your existing identity provider.

**If you host it yourself**, the operational half is yours:

- **Data-protection regulations (such as GDPR/CCPA):** your organization is the data controller. Initiative supports the technical side — export, erasure, access control, residency by choice of host — while lawful processing, consent, and records are organizational responsibilities. There is no third-party processor to sign an agreement with; *you* run it.
- **Formal certifications (such as SOC 2, ISO 27001, HIPAA):** achieved by your hosting and processes — key management, backups, monitoring, physical security, staff access.
- **Backups, disaster recovery, monitoring, and patching:** yours to run. See the [server guide](../running-a-server/index.md).

**If we host it**, the operational half is ours: running the service, backing it up, keeping it patched and current. What stays with you is what always stays with the organization using a tool — deciding what you collect, why you're allowed to, who in your group may see it, and answering the requests your own members make of you. Regulated data is worth a conversation before you commit to it rather than after.

!!! warning "No legal advice"
    This page describes capabilities, not a legal compliance guarantee. For regulated data, review your specific obligations with a qualified professional and document how your deployment meets them.

## A checklist for whoever runs the server

If compliance matters to your group, make sure you:

- [ ] Serve Initiative over **HTTPS** with a valid certificate.
- [ ] Set a **strong, unique server secret** and store it safely.
- [ ] Take **regular, tested backups** of the database and uploaded files.
- [ ] Keep Initiative **updated** to the latest release.
- [ ] Configure **trash retention** to match your data-retention policy.
- [ ] Prefer **single sign-on** so account lifecycle is managed centrally.
- [ ] Review who holds the **operator** and **owner** platform roles, who holds each community's admin and superadmin seats, and who can break glass.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md) — the technical isolation model.
- [Private messages](private-messages.md) — what end-to-end encryption covers.
- [Backups & updates](../running-a-server/backups-and-updates.md) — your operational responsibilities if you host it yourself.
- [Reporting a problem](reporting-a-problem.md) — responsible disclosure.
