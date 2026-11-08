---
icon: lucide/circle-help
---

# Frequently asked questions

Short answers to what people actually ask, with a pointer to the longer version if you want one.

## Starting out

??? question "Do I need to know project management to use this?"
    No, and please don't go and learn any first. A project is a board. A task is a to-do on it. That is genuinely enough to run real work, and always has been.

    Roles, tools, dashboards, plug-ins — all there when you need them, silent until then. See [Getting started](getting-started/index.md).

??? question "There's a lot here. Where do I begin?"
    Make a community. Make one initiative in it, named after what you're doing. Make one project. Put some tasks on it.

    That's it. You now have a working setup and you are allowed to stop. Come back for the rest of this only when something actually feels missing, which for a lot of groups is never. See [Your first community](getting-started/your-first-community.md).

??? question "Is it free?"
    Self-hosting is free and always will be. It's open source, and it's the complete product rather than a trimmed-down teaser.

    A paid hosted version is coming for people who'd rather not run a server, which is a completely reasonable thing to not want to do. See [Self-host or let us host it](self-host-or-hosted.md).

??? question "Is all of it open source?"
    The part you run is, under the AGPL — the app, every tool in it, the mobile builds.

    So are the [plug-in SDK](https://github.com/beyonders-studio/initiative-plugin-sdk) and the [GitHub plug-in](https://github.com/beyonders-studio/initiative-developer/tree/main/plugins/github), under MIT, if you fancy building a plug-in of your own.

    The pieces that exist only to run the hosted service are ours and stay closed. Nothing you self-host waits on them.

??? question "Can I add tools that aren't built in?"
    Yes — the **marketplace** has ready-made dashboards and plug-ins, and adding one takes a couple of clicks and no code. It holds what ships with Initiative plus whatever the person running your server has approved, so if something's missing, they're who to ask. See [Plug-ins & the marketplace](guides/plugins-and-marketplace.md).

    A few plug-ins need something set up behind them first. The **GitHub integration** runs inside Initiative, so there's no extra program to run; on your own server it needs a GitHub App, which is one button and a confirmation on GitHub. **Automations** are ours and live only on the hosted service. See [Plug-ins that need something running behind them](self-host-or-hosted.md#plug-ins-that-need-something-running-behind-them).

## Getting in

??? question "I can't find the community I was told to join"
    Most communities are private and don't appear anywhere at all until you're invited. You're not missing a search box — there's nothing to search.

    Ask whoever mentioned it for an invite link. That link takes you straight there once you've made an account.

    If your server runs a [community directory](guides/communities.md#finding-a-community-to-join), listed communities show up under **Join a community** on the rail. A community that hasn't listed itself won't be there however hard you look.

??? question "I don't see 'Join a community'"
    The directory is a server-wide feature that starts switched **off**, so plenty of servers don't have one. Everything there is invite-only.

??? question "My invite link doesn't work"
    Links can expire, run out of uses, or be switched off by an admin. None of this is a judgement on you as a person. Ask for a fresh one — it takes them about four seconds.

??? question "I don't see a 'Create community' button"
    Some servers turn community creation off on purpose so people join through invites instead. Ask a community admin to invite you, or whoever runs the server to make one for you.

??? question "The email never arrived"
    Give it a few minutes, then check spam. It is almost always spam.

    If it still hasn't turned up, the server may not have email configured at all — ask whoever runs it. Reset links also go stale, so if yours has been sitting there since Tuesday, request another. See [Signing in](getting-started/signing-in.md).

??? question "I've been signed out and can't get back in"
    Changing your password signs out every device — that one's deliberate. If you didn't change it, use **Forgot password** on the sign-in screen. If your server uses single sign-on there may be no password to reset; sign in the way you normally do.

??? question "It says password sign-in is turned off"
    Five wrong passwords or codes within fifteen minutes will do that, whoever typed them. Password and code sign-in switch off for fifteen minutes, and your email addresses get a note saying so. A second time the same day it's an hour; after that, four hours each time.

    Wait it out, or sign in with a passkey, which works the whole time. Or skip the wait: **Forgot password** on the sign-in screen emails you a link, and setting a new password from it turns sign-in straight back on.

## The age question

??? question "Why am I being asked my date of birth?"
    Because you're joining a community that anyone signed in can find — from the directory, or through an invite into one. Those are open to people you've never met, and you need to be **16 or older** to join one.

    You're asked once. The answer sticks to your account, so the second community asks nothing.

??? question "What happens to the date?"
    It's kept, encrypted, and used only to check age limits — a community's, or a plug-in's, which can differ by country. It's never shown back to anyone, you included, and it isn't sold or shared. Deleting your account deletes it.

??? question "It was just an invite from a friend. Why was I asked?"
    Because the community it leads to is a listed one — anyone signed in can find it. The question follows the community, not the way in.

    An invite to a community that hasn't listed itself never asks, and neither does anything else on Initiative.

??? question "I've been in this community for months and it's only asking now"
    Then nobody ever put the question to you: an admin added you, your workplace sign-in did, or the community listed itself after you joined. None of those had anyone at a keyboard to ask.

    So it asks at the door instead, once. Everything else — your other communities, the rest of Initiative — stays open while you decide.

??? question "My account can't reach anybody"
    <a id="my-account-cant-message-anyone"></a>

    If you can't join communities you can see, it's almost always the age question. Two things look alike:

    | What you see | What it is | What to do |
    |---|---|---|
    | A date-of-birth box when you click Join | You haven't answered yet | Answer it. Once. |
    | A box saying you told us you're not old enough | Your account answered as under 16 | Whoever runs the server can reset it — see below |

    Either way, everything inside the communities you already belong to still works, and so does the rest of Initiative. What the question stands in front of is joining a *listed* community.

    Extremely common, entirely fixable, and nobody is cross with you. Ask whoever runs your server to **reset the age question** — the box has an **Ask for help** button where the server takes help requests. Anyone on the support tier or above can do it, and it's recorded in the audit log like every other action taken on somebody's account.

    They can't see what you typed, incidentally, because it was never kept. Resetting simply lets you have another go.

    !!! info "Why you can't simply re-answer"
        A question you can retry until it comes out right isn't really a question. So the answer stands, and undoing it takes somebody else — which is why the reset is logged.

??? question "Can this be switched off?"
    Yes, by the platform owner under **Settings › Platform › Community**. Switching it off is the owner confirming that every account on the deployment belongs to someone 18 or older — which a company or school rollout knows and a public server doesn't. See [Data & compliance](security/data-and-compliance.md).

## Finding things

??? question "I can't find a project or file I know exists"
    Two likely reasons: you're in a **different community** (check the rail down the far-left edge), or it hasn't been **shared** with you. Fastest way to check is search — ++cmd+k++ / ++ctrl+k++ and type its name. See [Search & shortcuts](guides/search-and-shortcuts.md).

??? question "A link to something says 'not found' and I know it's there"
    If you're not a member of the initiative it lives in, Initiative hides it completely — so a direct link says "not found" rather than "access denied". Ask to be added to the initiative. See [Sharing & access](sharing/index.md).

??? question "My Tools doesn't show everything in my community"
    It isn't meant to. My Tools and My Calendar show what has reached *you*: shared with you, shared with a role you hold, or shared with everyone in an initiative you're in. It's a working list, not an inventory. Open a single initiative to see all of its work. See [Your space](guides/your-space.md#my-tools).

??? question "I'm a community admin. Why isn't every initiative in my sidebar?"
    Because navigation follows what you're *in*, not what you *may reach* — otherwise a community with a hundred initiatives buries the three you actually work in. Your authority hasn't changed: open any initiative and you see all of it. To keep one to hand, join it from the community front page (you walk straight in). See [Community admins join like everyone else](guides/initiatives.md#community-admins-join-like-everybody-else).

## Tasks and projects

??? question "Can a task have more than one person on it?"
    Yes, as many as you like. See [Projects & tasks](guides/projects-and-tasks.md).

??? question "I moved a task to another project and its status changed"
    Expected. Projects can each have their own statuses, so a moved task lands on the new project's default status. Set the one you want and carry on.

??? question "How do I clear out finished tasks without deleting them?"
    **Archive** them. There's a one-click "Archive done tasks", and you can filter archived tasks back into view whenever you want. Nothing is lost.

??? question "I deleted something by accident"
    It's fine. It's in the **Trash** — Community settings for shared things, your own Trash for your own items — and it sits there for a good while before going anywhere permanent.

    Go and get it back, and then go and have a cup of tea. See [Trash and retention](guides/communities.md#trash-and-retention).

??? question "An import didn't match people to their accounts"
    Exports and imports identify people by **handle** (`foobar#1234`), because a handle is the same in every community and an email address isn't. A file that names people by email address won't match anyone, so export it from Initiative again. See [Exporting a project](guides/projects-and-tasks.md#exporting-a-project).

## Your account

??? question "Can I change my username?"
    Not on your own — your handle is how people find and mention you, so changing it is a job for whoever runs the server. What you *can* change any time is your **display name**, one per community — see [Your name in a community](guides/communities.md#your-name-in-a-community).

??? question "Why does my name show in one community and not another?"
    A display name belongs to the community you set it in. Every other community shows your handle until you set one there too, with **Set your display name** at the top of its **Members** page.

??? question "Due dates and reminders are a few hours off"
    Your **timezone** is wrong. It's almost always the timezone. Fix it in **My Settings → Preferences** and everything snaps back into place.

??? question "I'm getting too many (or too few) emails"
    Tune them row by row in **My Settings → Notifications**, one row for each way something involves you, each with its own **Bell**, **Email**, **Mobile** and **Desktop** switch, and there's no minimum. A community you'd rather hear less from has its own switches, and **Mute**. **Do not disturb**, further down, has **Quiet hours** and **Pause notifications**. See [Notifications](guides/notifications.md).

??? question "How do I leave a group?"
    On the community rail, open the community's menu and choose **Leave community**. Members and admins leave freely. If you're the community's only **superadmin**, you'll be made to hand the seat to somebody else first — you can't simply slip out and leave nobody holding the keys.

??? question "My account says it's suspended"
    You can sign in, and you get one screen: that you're suspended, the reason the moderator gave if they gave one, and how to appeal. Nothing else opens while it lasts — not your communities, not your own settings.

    Where the server takes appeals, **Appeal** on that screen sends one to its moderators. You follow it on the same screen, and they can write back to you there; you can have one appeal open at a time, and appeal again once it's closed. Where the server takes none, the screen gives the address to write to instead.

    Nothing is taken away. Memberships, work, everything you wrote stays exactly where it is, and lifting the suspension hands the account back whole.

??? question "One of my communities has a lock on it"
    It's suspended. Nobody in it can open it while that lasts, its admins included, which is why you're looking at a lock rather than the usual front page. Opening it says who to contact, with **Ask for help** where the server takes help requests.

    Nothing inside has been changed or deleted, and it all comes back as it was when the suspension is lifted. Members don't see the community at all in the meantime, so if people ask where it went, now you know.

??? question "What's the difference between deactivating and deleting my account?"
    **Deactivating** is reversible — switched off, data kept. **Deleting** is permanent, and you choose whether your past contributions are anonymized or removed outright. See [Closing your account](account/profile-and-preferences.md#closing-your-account).

## Privacy and data

??? question "Can everyone in my community see everything in it?"
    No. Being in a community doesn't hand you its contents.

    An **initiative** is only visible to the people added to it, and individual projects and files narrow it down further still. The one exception is a **community admin**, who can see everything in their own community, because somebody has to be able to. See [Sharing & access](sharing/index.md).

??? question "How do I keep something visible to just two or three people?"
    Put it in an initiative with only those people in it.

    That's the strongest everyday boundary in the whole app, and it needs no configuration whatsoever — everybody else simply doesn't have it. To narrow further inside an initiative, share the specific project or file.

??? question "Can other groups on the same server see our stuff?"
    No. Each community's data is separated at the database level. See [How your data is kept separate](security/how-your-data-is-kept-separate.md).

??? question "Can a community admin, or whoever runs the server, read our private initiative?"
    A **community admin** can see everything in their own community — that's part of running it. Platform staff on a hosted service get in only through **temporary, recorded** access that expires on its own. See [Platform roles](running-a-server/platform-roles.md).

??? question "Can a community admin read my direct messages?"
    No. Messages are end-to-end encrypted, so they're readable on the devices in the conversation and nowhere else — not by an admin, not by whoever runs the server, not by us. They're also not community content, so they're not in exports or search. See [Private messages](security/private-messages.md).

??? question "Can I message more than one person at once?"
    Yes — start a conversation and keep adding people. Everyone is asked before anything reaches them, nobody can be added to it afterwards, and it's called by who's on it rather than having a name. See [Talking to a few people at once](guides/messages.md#talking-to-a-few-people-at-once).

??? question "Why don't my messages show up on my new phone?"
    Because there's no copy on the server for it to catch up from — that's what end-to-end encryption costs. Each device keeps its own history from the moment it joined a conversation, and signing out of a browser takes its copy with it. See [Your messages live on your devices](guides/messages.md#your-messages-live-on-your-devices).

??? question "Somebody posted something that shouldn't be there"
    Use **Report** on it. It's on comments, notices, pictures, profiles and directory listings, and it goes to the right people by itself: anything a community holds reaches that community's moderators, and anything about an account reaches whoever runs the server.

    Private messages are never moderated, so they carry no Report. To stop hearing from somebody there, ignore them under **My Settings → Privacy → Ignored accounts**.

??? question "Where is my data stored?"
    If you host Initiative yourself: wherever your server runs, and that's your call. If we host it: where our service runs. Either way it stays yours. See [Data & compliance](security/data-and-compliance.md).

??? question "Can I get my data out?"
    Yes. Every tool you own exports from its **Settings → Advanced**: projects to a portable file, spreadsheets to CSV or Excel, calendars to `.ics`, and so on. See [Getting your data out](security/data-and-compliance.md#getting-your-data-out).

## If you run the server

??? question "How do I update to a new version?"
    Back up, then `docker compose pull` and `docker compose up -d`. Migrations run themselves. See [Backups & updates](running-a-server/backups-and-updates.md).

??? question "What do I need to back up?"
    The database and the uploads, together and regularly — plus keep your `SECRET_KEY` somewhere safe so a restore can actually decrypt.

??? question "Can I connect our company login?"
    Yes — Initiative speaks OIDC, including mapping your provider's groups to communities and roles. See [Single sign-on](running-a-server/single-sign-on.md).

## Still stuck?

Look at the bottom of the sidebar. The question mark opens these pages, and where there's somebody to ask — a server that takes help requests, or one with an address to write to — the lifebuoy beside it is **Ask for help**.

To share an idea, something that got in your way, or something you love with the people who run the server, choose **Send feedback** in your account menu or the command palette.

If it looks like the software rather than your account, see [Reporting a problem](security/reporting-a-problem.md).

If it's about one specific community — who's in it, what you can reach, why something's vanished — ask that community's admins first. They can see and fix far more of it than whoever runs the server can, and they're usually quicker to answer.
