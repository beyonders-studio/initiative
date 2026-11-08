---
icon: lucide/circle-help
---

# Frequently asked questions

Short answers to what people actually ask, each with a pointer to the longer version if you want it.

## Starting out

### Do I need to know project management to use this?

No, and please don't go learn any first. A project is a list of tasks, and a task is one thing somebody has to do. That's enough to run real work, and everything else stays out of your way until you go looking for it. See [Getting started](getting-started/index.md).

### There's a lot here. Where do I begin?

Make or join a community, make one initiative in it named after what you're doing, put one project in that, and add a few tasks. That's a working setup, and you're allowed to stop there.

Come back for the rest when something feels missing, which for plenty of groups is never. See [Your first community](getting-started/your-first-community.md).

### Is it free?

Hosting it yourself is free. It's open source, and it's the complete product rather than a trimmed-down teaser.

If you'd rather not run a server, Initiative Cloud is the paid version we host for you. See [Self-host or let us host it](self-host-or-hosted.md).

### Is all of it open source?

Everything in the app you run is, under the AGPL-3.0: the server, the web app, and the phone and desktop apps.

The [plug-in SDK](https://github.com/beyonders-studio/initiative-plugin-sdk) and the [plug-in registry](https://github.com/beyonders-studio/initiative-developer), which includes a GitHub plug-in to start your own from, are under the MIT license, in case you want to build a plug-in of your own.

### Can I add tools that aren't built in?

Yes. The **Marketplace** has ready-made dashboards, projects and plug-ins, and adding one takes a couple of clicks and no code. It holds what ships with Initiative plus what the person running your server lets in, so if something's missing, they're who to ask.

A dashboard or a project goes into an initiative like anything else you make. A plug-in is added to the whole community, by its superadmin. A few plug-ins connect to another service and need setting up on the server first; see [Plug-ins that need something running behind them](self-host-or-hosted.md#plug-ins-that-need-something-running-behind-them). More in [Plug-ins & the marketplace](guides/plugins-and-marketplace.md).

## Getting in

### I can't find the community I was told to join

Most communities are invite-only and don't show up anywhere until you're invited, so there's nothing to search for. Ask whoever mentioned it for an invite link, which takes you straight there once you've made an account.

If your server has a community directory, listed communities show up under **Join a community** on the rail. A community that hasn't listed itself won't be there however hard you look. See [Find a community to join](guides/communities.md#finding-a-community-to-join).

### I don't see "Join a community"

Your server doesn't run a community directory. It starts switched off, and whoever runs the server decides whether to turn it on, so on plenty of servers every community is invite-only.

### My invite link doesn't work

Invite links can expire, run out of uses, or be deleted by an admin, and a link made for one person stops working once somebody has used it. None of this is a judgment on you as a person. Ask for a fresh one, which takes them about four seconds.

### I don't see a "Create Community" button

Some servers turn community creation off, so people join through invites instead. Ask a community admin to invite you, or ask whoever runs the server to make a community for you.

### The email never arrived

Give it a few minutes, then check your spam folder, which is where it almost always turns out to be.

If it still hasn't turned up, the server may not have email set up, so ask whoever runs it. A password reset link lasts an hour and works once, so if yours has been sitting there since Tuesday, ask for another. See [Signing in](getting-started/signing-in.md).

### I've been signed out everywhere

Changing your password signs out your other devices and switches off your API keys, and setting a new one from a reset link signs out every device. That's on purpose.

If you didn't change it, use **Forgot password?** on the sign-in screen to set a new one. If your server uses single sign-on, you may not have a password to reset, so sign in the way you normally do.

### It says password sign-in is turned off

Five wrong passwords or codes within 15 minutes turn password and code sign-in off for 15 minutes, whoever typed them, and your email addresses get a note saying so. A second lock within a day lasts an hour, and after that it's four hours each time.

You don't have to wait it out. A passkey works the whole time, and so does any device that's already signed in. Or use **Forgot password?**, because setting a new password from the emailed link turns sign-in straight back on. Whoever runs the server can turn it back on for you too.

## The age question

### Why am I being asked my date of birth?

Some communities and plug-ins have a minimum age, so a server that checks age asks every account once. That happens when you sign up, or the next time you open Initiative if your account doesn't have a date yet. Once you've answered, you're never asked again.

### What happens to the date?

It's kept encrypted and used only to check age limits. It isn't shown to anybody, the people who run the server included, and it's never sold. It's erased along with your account.

### What does my age change?

On a server that checks age:

| If you're | Then |
|---|---|
| Under the minimum age for an account where you live (between 13 and 16, depending on the country) | You can't have an account on that server |
| Under 16 | You can't join communities that list themselves in the directory, or send private messages |
| Under a plug-in's minimum age | That plug-in won't open for you, and its minimum can differ by country |

A community you were invited to that hasn't listed itself works the same at any age.

### I entered the wrong date

The answer stands, because a question you can retry until it comes out right isn't much of a question. Whoever runs your server can reset it for you, which also erases the date you gave, and the reset is recorded. Where your server takes help requests, the message telling you you're not old enough has **Ask for help** on it.

This is extremely common, and nobody is mad at you.

### A community I'm in says I'm not old enough

That community has listed itself in the directory, which opens it to anyone signed in, and listed communities are for people 16 and older. If your account answered under 16, that community stays closed to you while it's listed. Your other communities and the rest of Initiative carry on as normal. If the date you gave was wrong, see the answer above.

### Can the age check be switched off?

Yes, by the server's owner, with **Check members' age** under **Platform Settings** › **Community**. Turning it off is the owner confirming that everyone on the server is 18 or older, which a company or a school knows and a public server doesn't. See [Data & compliance](security/data-and-compliance.md).

## Finding things

### I can't find a project or file I know exists

Usually you're in a different community (check the rail down the left edge), or it hasn't been shared with you. The fastest check is search: press ++cmd+k++ or ++ctrl+k++ and type its name. If it might be archived, turn on **Include archived**. See [Search & shortcuts](guides/search-and-shortcuts.md).

### A link says "not found" and I know the thing exists

If you're not in the initiative it lives in, Initiative hides it completely, so a direct link says "not found" rather than "access denied". Ask to be added to the initiative.

If you are in the initiative and the thing just hasn't been shared with you, the link says **You need access** instead, and **Request access** asks whoever can share it. See [Sharing & access](sharing/index.md).

### My Tools doesn't show everything in my community

It isn't meant to. **My Tools** and **My Calendar** show what has reached you: things shared with you, with a role you hold, or with everyone in an initiative you're in. They're a list of your work rather than an inventory of the community, and being an admin doesn't widen them.

To see everything in one initiative, open the initiative. See [Your space](guides/your-space.md#my-tools).

### I'm a community admin. Why isn't every initiative in my sidebar?

Your sidebar follows what you're in, rather than everything you could open, so a community with a hundred initiatives doesn't bury the three you work in. You can still open any initiative and see all of it.

To keep one in your sidebar, join it. **Join** on the community front page lets you straight in, even where other people have to ask. Invite-only initiatives aren't listed there, so for one of those, make yourself one of its **Project managers** under **Community Settings** › **Initiatives**. See [Initiatives](guides/initiatives.md).

## Tasks and projects

### Can a task have more than one person on it?

Yes, as many as you like, as long as each of them can open the project. See [Projects & tasks](guides/projects-and-tasks.md).

### I moved a task to another project and its status changed

That's expected. Each project can have its own statuses, so a moved task lands on the new project's default one. Set the status you want and carry on.

A move also takes off anybody assigned who can't open the new project, and a task moved into another initiative leaves its custom fields behind.

### How do I clear out finished tasks without deleting them?

Archive them. **Archive done tasks** sits under the task table and at the bottom of each done column on the board, and it asks before it does anything.

To see archived tasks again, open **Filters** and turn on **Show archived**. Nothing is lost.

### I deleted something by accident

It's fine. Everything you deleted is under **My Settings** › **Trash**, ready to restore. Community admins also have the community's whole trash, under **Community Settings** › **Trash**.

Things wait there for 90 days unless the community chose a different period, and you can put them back any time before then. Go get it, and then go get a coffee. See [Bring back something deleted](guides/running-a-community.md#trash-and-retention).

### An import didn't match people to their accounts

Initiative's own exports name people by their handle (`jordan#1234`), because a handle is the same in every community and an email address isn't. An import matches people by exact handle, so a file that names them some other way won't match anyone. Export it from Initiative again and import that file. See [Projects & tasks](guides/projects-and-tasks.md).

## Your account

### Can I change my username?

Not by yourself. Your handle is how people find and mention you, so changing it is up to the server's staff, and the number after it stays the same. The one exception is an account that was given a username automatically, whose owner gets to pick a name once.

What you can change any time is your display name, which you set separately in each community. See [Choose your name in a community](guides/communities.md#your-name-in-a-community).

### Why does my name show in one community and not another?

A display name belongs to the community you set it in. Every other community shows your handle until you set one there too, with **Set your display name** at the top of its **Members** page.

### Due dates and reminders are a few hours off

Check your time zone, because it's almost always the time zone. Fix it under **My Settings** › **Preferences** › **Timezone** and everything snaps back into place.

### I'm getting too many (or too few) emails

Tune them under **My Settings** › **Notifications**. **What you hear about** has a row for each way something can involve you, and each row has its own **Bell**, **Email**, **Mobile** and **Desktop** switch. **Email arrives** can gather your email into one message an hour, a day or a week.

A community you'd rather hear less from has its own row under **Per community**, with **Mute**. **Do not disturb** holds **Quiet hours** and **Pause notifications**. See [Notifications](guides/notifications.md).

### How do I leave a community?

Right-click the community on the rail, or press and hold it on a phone, and choose **Leave community**. Anything you owned there is left for an admin to hand on.

If you're the community's only superadmin, you'll need to make somebody else superadmin first, unless nobody else is in it. See [Communities](guides/communities.md).

### My account says it's suspended

You can still sign in, and you'll see one screen: that you're suspended, the reason if the moderator gave one, and how to appeal. Nothing else opens while it lasts, your communities and your own settings included.

Where the server takes appeals, **Appeal** on that screen sends one to its moderators. You follow it on the same screen, and they can write back to you there. You can have one appeal open at a time, and appeal again once it's closed. Where the server takes none, the screen tells you who to contact instead.

Nothing is taken away. Your memberships and your work stay where they are, and lifting the suspension hands the account back whole.

### One of my communities has a lock on it

It's suspended, and nobody can open it while that lasts, its admins included. Opening it says who to contact, with **Ask for help** where the server takes help requests.

If you can see the lock, you're one of its admins. Everybody else doesn't see the community at all for now, so if people ask where it went, now you know. Nothing inside has been changed or deleted, and it all comes back as it was when the suspension is lifted.

### What's the difference between deactivating and deleting my account?

**Deactivating** switches your account off and keeps it. Your name, email and work stay put, but you're taken out of every community, and only whoever runs the server can switch the account back on.

**Deleting** makes your account disappear for everyone straight away, and erases it after a while (30 days, unless your server says otherwise). Sign back in before then and the deletion is called off. Once it's erased, your projects pass to other people, and your comments and files stay under "Deleted user".

Both are at the bottom of **My Settings** › **Account**, under **Close your account**. See [Profile & preferences](account/profile-and-preferences.md).

## Privacy and data

### Can everyone in my community see everything in it?

No. An initiative's work is visible only to the people in it, and each project or file can be narrowed further. The exception is community admins, who can open everything in their own community, because somebody has to be able to. See [Sharing & access](sharing/index.md).

### How do I keep something visible to just two or three people?

Put it in an initiative with only those people in it. That's the strongest everyday boundary in Initiative, and it needs no setup, because everybody else isn't in the initiative to begin with.

To narrow something down inside an initiative, change its sharing. New things start out readable by everyone in the initiative, so switch it to **Restricted** and add the people you want. See [Sharing](sharing/sharing-projects-and-files.md).

### Can other groups on the same server see our stuff?

No. Each community's data is kept apart at the database level. See [How your data is kept separate](security/how-your-data-is-kept-separate.md).

### Can a community admin, or whoever runs the server, read our private initiative?

A community admin can open everything in their own community, which is part of running it. Server staff get in only through a grant that has a time limit, leaves a record and expires on its own. See [Platform roles](running-a-server/platform-roles.md).

### Can a community admin read my private messages?

No. Messages are end-to-end encrypted, so they can be read on the devices in the conversation and nowhere else. That rules out an admin, whoever runs the server, and us. They aren't community content either, so they never turn up in an export or in search. See [Private messages](security/private-messages.md).

### Can I message more than one person at once?

Yes, up to 40 people in one conversation. Everyone has to be somebody the others can message, everyone is asked before anything reaches them, and nobody can be added once it has started. See [Messages](guides/messages.md).

### Why aren't my messages on my new phone?

There's no copy on the server for it to catch up from, which is what end-to-end encryption means. When a new device signs in, your other devices ask you to verify it, and choosing **Send it my message history** there brings it up to date. Signing out of a browser deletes that browser's copy. See [Your messages live on your devices](guides/messages.md#your-messages-live-on-your-devices).

### Somebody posted something that shouldn't be there

Use **Report** on it. You'll find it on comments, posts, events, wiki pages, profiles, community listings in the directory, and the marketplace.

A report finds the right people by itself. Anything inside an initiative goes to that initiative's moderators, and anything about an account, a community listing or the marketplace goes to whoever runs the server.

Private messages can't be reported, because nobody outside the conversation can read them. To stop hearing from somebody there, choose **Ignore** on them. Everyone you've ignored is listed under **My Settings** › **Privacy** › **Ignored accounts**.

### Where is my data stored?

If you host Initiative yourself, it's wherever your server runs, and uploads go to a folder or to S3-compatible storage, whichever you set up. On Initiative Cloud, it's with us. Either way it stays yours. See [Data & compliance](security/data-and-compliance.md).

### Can I get my data out?

Yes. Each project, file and other tool exports from its own **Settings** › **Advanced** › **Export**, for whoever can delete it. Projects come out as an importable file, PDF, CSV or Excel, spreadsheets as CSV, Excel or JSON, calendars as iCalendar (`.ics`), and text documents as PDF, Markdown or Word.

A community's superadmin can also export the whole community at once, from **Community Settings** › **Data**. See [Data & compliance](security/data-and-compliance.md).

## If you run the server

### How do I update to a new version?

Back up first, then run `docker compose pull` and `docker compose up -d`. Database changes run on their own when the new version starts. See [Backups & updates](running-a-server/backups-and-updates.md).

### What do I need to back up?

The database and the uploads (a folder, or your S3-compatible storage), together and regularly. Keep your `SECRET_KEY` somewhere safe too, because some stored data is encrypted with it, and a restore can't read that data without the same key.

### Can people sign in with our company's accounts?

Yes, through any identity provider that speaks OpenID Connect (OIDC). The groups people belong to there can decide which communities and roles they land in, and a community's superadmin can connect a provider for just that community. See [Single sign-on](running-a-server/single-sign-on.md).

## Still stuck?

Inside the app, open **Help** from your account menu (under your name and picture at the bottom of the sidebar), from search, or from the question mark in the desktop app's title bar. It searches these pages without taking you away from what you were doing. If nothing answers it, **No answer here?** under the results shows how to ask, either with **Ask the team** or with an address to write to, depending on your server.

To send an idea, a gripe or some praise to the people who make Initiative, choose **Send feedback** in your account menu or in search, where your server offers it.

If it's about one community (who's in it, what you can reach, why something vanished), ask that community's admins first. They can see and fix far more of it than whoever runs the server, and they usually answer faster.

If it looks like a bug in Initiative itself, tell us on [GitHub](https://github.com/beyonders-studio/initiative/issues). For anything to do with security, see [Reporting a problem](security/reporting-a-problem.md) instead.
