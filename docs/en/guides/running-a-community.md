---
icon: lucide/settings
---

# Running a community

Whoever makes a community runs it, at least until they hand some of the work to other people. This page walks through all of it: making a community, inviting people, deciding who does what, and the settings that keep the place tidy. Nearly everything here can be changed back, and the one thing that can't, deleting the whole community, makes you type a sentence first. So poke around.

If you're looking for the everyday stuff (switching communities, joining one, leaving one), that's on [Communities](communities.md).

## Who can do what in a community

Everybody in a community holds one **community role**, which decides how much of running the place is theirs.

| Role | What they can do |
|---|---|
| **Member** | Take part in the initiatives they're in. Most people are members. |
| **Admin** | Run the community: its members, invites, initiatives and settings. An admin can open and change everything in the community, including initiatives they haven't joined and things nobody shared with them. |
| **Superadmin** | Everything an admin does, plus the community's own sign-in, its AI and plug-ins, exporting it whole and deleting it. Whoever makes a community starts as its superadmin. |
| **Guest** | Here for a set number of days, seeing only what their invite gave them. See [Guests](../sharing/guests.md). |

Being an admin of your community gives you no say over the server it runs on, or over anybody else's community. Server-wide roles are a separate thing: see [Platform roles](../running-a-server/platform-roles.md).

## Make a community

Anyone can make a community, unless whoever runs your server has switched that off. Then the **+** isn't on your rail, and the people who manage communities on the server can make one for you. A server can also cap how many communities one account makes in a day.

1. Select **Create Community**, the **+** near the bottom of the community rail.
2. Type a **Community name**, usually just what your group is called.
3. Add a **Description** if you like.
4. Select **Create community**.

You land inside your new community as its superadmin, with the **New initiative** window already open, because an empty community's first job is naming the work it's for. Close it if you'd rather look around first; [Initiatives](initiatives.md#make-an-initiative) covers it when you're ready.

## Open Community settings

Admins, and anyone whose [custom role](#custom-roles) gives them part of the job, can open Community settings. Select the gear beside the community's name at the top of the sidebar, or right-click the community's icon on the rail and choose **Community Settings**.

Which tabs you see depends on what you hold:

| Tab | What's in it | Who sees it |
|---|---|---|
| **Usage** | Storage, members and guests against the community's limits. | Superadmins |
| **Community** | Name, description, location, pictures and the directory listing. | Admins |
| **Users** | Invite links and the member list. | Admins |
| **Roles** | [Custom roles](#custom-roles). | Admins |
| **Guests** | Guest invites and the guests here now. Only where the server allows guests. See [Guests](../sharing/guests.md). | Admins |
| **Security** | The community's own sign-in rules. Only where the server has granted it, which most communities never need. See [Your community's sign-in and security](../security/community-security.md). | Superadmins |
| **Initiatives** | Every initiative in the community, and rules for all of them. | Admins |
| **Integrations** | AI settings and plug-ins. See [AI features](../account/ai-features.md) and [Plug-ins & the marketplace](plugins-and-marketplace.md). | Superadmins |
| **Trash** | Everything deleted in the community, ready to restore. | Admins |
| **Data** | Exporting the whole community, and bringing work in. | Superadmins |
| **Danger zone** | Deleting the community. | Superadmins |

A custom role changes this: a member whose role holds a job sees that job's tab, and an admin whose role narrows them sees only the tabs for the jobs they hold.

## Change the community's name, picture and banner

Admins can do this, and so can anyone whose custom role includes **Profile**.

1. Open Community settings and select **Community**.
2. Change the **Name** or **Description**.
3. Select **Save changes**.
4. Under **Pictures**, choose an image for the **Icon**. It's cropped square for you.
5. Choose an image for the **Banner**. It's cropped to a wide strip, and something around 2400 × 600 looks best.

Pictures save as soon as you pick them. Below the banner you can set the **Banner fill** (the color that shows when there's no banner image), whether the **Banner text** is light or dark, the **Banner text position** and the **Banner fade**. **Reset to default** puts the colors back. The icon is what members see on their rail, so pick something they'll recognize from across the room.

## Say where your community is

Some communities are about a place, like the youth soccer league, or the Thursday trivia team that meets at the one bar with parking. **Location** says where, as vaguely or exactly as you like. Admins can set it, and so can anyone whose custom role includes **Profile**.

1. Open Community settings and select **Community**.
2. Under **Location**, start typing in **Where**.
3. Pick a suggestion from the list, so the community goes on the map.
4. Type a **Place name** if you want one, like "Queen Anne Neighborhood".
5. Select **Save location**.

The location shows on your front page and on your community's card, exactly as typed, and tapping it on the front page opens a map. Picking a suggestion is what lets people searching **Near me** find you. A place the list has never heard of, like "the old mill", still shows on the card; it just can't be near anyone. **Remove location** takes it off.

!!! warning "Listed means anyone can see it"
    A [listed](#listing-your-community-admins) community shows its location to everyone browsing the directory. If you meet in somebody's living room, the city is plenty.

??? techspec "Where the suggestions come from"
    The places are [GeoNames](https://www.geonames.org/) data (every town of a thousand people or more) that ships with the app, so typing a place sends nothing anywhere. Suggestions start from the place already picked, or else from the city your device's time zone is named after. A picked place saves its country and coordinates, and **Near me** measures the distance between those.

## List your community in the directory { #listing-your-community-admins }

A listed community appears in the [community directory](communities.md#finding-a-community-to-join), where anyone signed in on your server can find it. Admins can list their community, on servers that run a directory, and choose whether people join straight away or ask first.

1. Open Community settings and select **Community**.
2. Under **Community directory**, set **Who can join**:
    - **Listed: anyone can join** lets people in with one click.
    - **Listed: ask to join** has them send a request, which an admin approves.
3. Under **Pick at least one category**, tick the subjects your community is about.
4. Read the list, then tick **This community contains no adult content**.
5. Select **List this community**.

Your community shows up in the directory straight away, under the categories you picked. Change them later under **Categories** in the same place. Switch between the two listed choices whenever you like; set **Who can join** to **Invite only** to unlist it, and nothing else changes. Invite links work whichever you choose.

That tick is a promise, and keeping it is the admins' job: a community that stops meeting it is taken out of the directory. Two other things keep a community out: a member limit of one person, since nobody else could ever join, and a member who has told Initiative they're under 16.

### Answer requests to join { #answer-requests-to-join }

A community set to **Listed: ask to join** collects requests. Admins, and anyone whose custom role includes **Members**, get a notification when someone asks.

1. Open Community settings and select **Users**.
2. Under **Requests to join**, read who's asking and the note they left.
3. Select **Approve** to make them a member, or **Deny** to turn them down.

They get a notification with your answer. Someone turned down can ask again. A request your community has no room for stays in the list until it does.

### Give newcomers somewhere to land

Joining a community puts nobody in an initiative, and an initiative's contents stay hidden until you're in it. So once you're listed, if none of your initiatives welcomes newcomers, a box called **New members will arrive to an empty community** appears under the listing.

1. Choose an initiative in **Initiative for new members**.
2. Select **Set as the landing initiative**.

That initiative becomes open to anyone in the community, and everyone who joins the community from now on is added to it automatically. People already here aren't added. [Initiatives](initiatives.md#add-every-new-community-member-automatically) has the same switch for any initiative.

## Invite people with a link { #inviting-people }

Admins can make invite links, and so can anyone whose custom role includes **Invites**. Each link can be used a set number of times before a set date.

1. Select **Invite members** on the community's front page, beside the member count. It's also at the top of the **Members** page and on the **Users** tab of Community settings.
2. Set **Max uses**: how many people can join with this one link.
3. Set **Expires in (days)**: how long it works.
4. Select **Generate invite**.
5. Select **Copy invite link**, the copy button beside the new link.
6. Send the link however you like: email, text, the group chat.

Copy it now, because the full link is only shown once. The invite then appears in the list below, with how many times it has been used and when it expires. Anyone who opens the link joins after signing in or making an account. A new link starts at one use and seven days; leave the days at 0 and it still runs out after seven.

For a quick one, right-click the community's icon on the rail and choose **Invite members**. That copies a fresh link for one person, good for seven days.

When every seat in the community is taken, no new invite can be made. Remove somebody, or ask whoever runs your server to raise the limit.

Somebody who needs one project for three weeks, rather than the whole community for good, is better off as a [guest](../sharing/guests.md).

### Stop an invite link working

1. Open the invites: **Invite members**, or Community settings and **Users**.
2. Select **Delete invite**, the trash can beside the link.

The link stops working straight away. People who already joined with it stay.

## Make someone an admin

Admins can change other people's community roles. An admin whose custom role narrows them can't make or unmake admins, and only a superadmin can change a superadmin. Nobody can change their own role.

1. Open Community settings and select **Users**.
2. Find the person, using **Filter by handle...** if the list is long.
3. In their **Community role**, choose **Admin**.

You can do the same from the **Members** page: open the person's menu, choose **Community role**, then **Admin**.

Making someone an admin also moves them up in every initiative they're already in: they become a Moderator there, unless they're already a Project Manager or Moderator. That way they hear about join requests like the authority they now are. Making an admin a member again leaves their initiative roles where they are, Moderator included, so check their initiatives if they shouldn't keep it.

## Pass the superadmin seat to someone else { #why-superadmin-is-separate }

Running a community and holding its keys are different jobs. Your most reliable organizer is the person you want as an admin. They aren't necessarily the person you want changing how everybody signs in, or able to delete the whole community at 11pm. So the superadmin seat sits above admin, and it holds only those few things: the community's sign-in and security, its AI and plug-ins, exporting it whole and deleting it.

Only a superadmin can make somebody else a superadmin, which also means nobody can take the seat from you.

1. Open Community settings and select **Users**.
2. In the person's **Community role**, choose **Superadmin**.

A community can have more than one superadmin. To step down yourself, make somebody else a superadmin first, then ask them to change your role, since you can't change your own.

**A community always keeps one.** Its last superadmin can't be made an admin, be removed, leave, or close their account while anybody else is still in it. The exception is the obvious one: if you're the only person left, there's nobody to strand, so you're free to go.

## Remove someone from the community

Admins can remove people, and so can anyone whose custom role includes **Members**. Removing an admin takes an admin who holds every part of the job, and only a superadmin can remove a superadmin. You can't remove yourself this way; [leave](communities.md#leave-a-community) instead.

1. Open Community settings and select **Users**, or open the **Members** page.
2. Open the person's menu.
3. Select **Remove from community**.
4. Select **Remove from community** again to confirm.

They lose access to every initiative and everything in the community. Anything they owned stays, with nobody owning it, until an admin [claims it](#hand-someones-things-to-another-admin). Their account is untouched, and they can only come back with a new invite, or through the directory if the community is listed.

## Set someone's display name

Members choose their own [display name](communities.md#your-name-in-a-community). Admins can set or clear it for them, and so can anyone whose custom role includes **Members**.

1. Open the **Members** page, or Community settings and **Users**.
2. Open the person's menu.
3. Select **Set display name**.
4. Type the name in **Display name**, or clear it to go back to their handle.
5. Select **Save**.

## Hand someone's things to another admin

Everything in Initiative has an owner: whoever made it. When someone moves on, an admin can move what they own to another admin. When someone leaves or is removed, what they owned is left with no owner, and an admin can claim it. Admins can do both, and so can anyone whose custom role includes **Members**.

To move what one person owns:

1. Open Community settings and select **Users**.
2. Open the person's menu.
3. Select **Transfer ownership**.
4. Choose the **New owner**.
5. Select **Transfer**.

To claim what nobody owns:

1. Open Community settings and select **Users**.
2. Under **Unowned content**, select **Claim all**.
3. Choose the **New owner**.
4. Select **Transfer**.

The new owner has to be a community admin. A plug-in can also take ownership, where it's switched on and allowed to change that content. Admins can already open everything in the community, so moving ownership never shows anybody something new.

## Export the member list

1. Open Community settings and select **Users**.
2. Select **Export all as CSV**.

You get one row per member: their handle, display name, community role, whether they came in through your group's sign-in, whether their account is active, when it was made, and their role in each initiative. For one person, open their menu and choose **Export**. A member's server-wide role and email address aren't the community's business, so they're not in it.

## Give someone part of the job with a custom role { #custom-roles }

The person who should send out invites isn't always the person who should be able to delete the spring play. A **custom role** is a named handful of the jobs of running the community, given to one person at a time. "Door person" might be a role that holds nothing but **Invites**. Most communities never need one, and if yours doesn't, the **Roles** tab just stays empty.

A custom role is for one of two kinds of people:

| A role for… | Does |
|---|---|
| **Members** | Gives a member some jobs on top of what they already do. |
| **Admins** | Narrows an admin to the jobs it holds. They still see everything in the community; they just can't run the parts left out. |

Admins can make roles, and so can anyone whose own custom role includes **Roles**.

1. Open Community settings and select **Roles**.
2. Select **Add role**.
3. Type a **Name**.
4. In **For**, choose **Members** or **Admins**. This can't be changed once the role is made.
5. Under **What it holds**, tick the jobs it includes.
6. For a role for admins, tick under **What it holds of the plug-ins** the parts of your plug-ins it keeps, such as a plug-in's settings page.
7. Select **Add role**.

To give somebody a role:

1. Open Community settings and select **Users**.
2. In the person's **Custom role**, choose the role.

You can also open the person's menu on the **Members** page and choose **Custom role**. Choose **None** to take a role off.

| Job | Lets them | On a members' role? |
|---|---|---|
| **Profile** | Change the community's name, picture, banner and description. | Yes |
| **Invites** | Make and delete invite links, guest invites included. | Yes |
| **Members** | Change people's roles and names, remove them, and give custom roles. | Yes |
| **Initiatives** | Create, archive and delete any initiative, and run ones they are not in. | No |
| **Community calendars** | Add and change the community's own calendars. | Yes |
| **Community contacts** | Add and change the community's own contacts, and move an initiative's contacts into them. | Yes |
| **Webhooks** | Set up the community's webhooks. | No |
| **Trash** | Restore or delete for good anything in the community's trash. | No |
| **Usage** | See what the community uses against its limits. | Yes |
| **Roles** | Add, change and delete custom roles. | No |

A few rules keep it fair:

- **One role each.** A role only counts while its holder is still a member or an admin, whichever it was made for, so making an admin a member again quietly sets their admin role aside. Somebody who leaves and comes back starts with none.
- **Plug-ins follow the admins' roles.** Admins hold everything your plug-ins add to Community settings, and an admin's role keeps only the parts it lists. A role for members holds none of it.
- **Nobody hands out more than they hold.** You can't make, change or give a role that holds a job, or a part of a plug-in, you don't. Taking an admin's role off gives them every job back, so only an admin who holds every job can do that.
- **Guest invites stay with admins**, even for a member whose role holds **Invites**, because a guest can be let into any initiative.
- **Settings are optional.** Invites and the member list also work from the front page and the **Members** page, so your door person never has to go looking for Community settings.

Deleting a role sends everyone who held it back to their plain role. Whoever runs your server can close custom roles for a community; the roles you have keep working, but nobody can change them.

## Run the community's initiatives

An [initiative](initiatives.md) is one effort inside the community, with its own people and its own tools. Admins can see and run every initiative from one table, including the ones they haven't joined. Anyone whose custom role includes **Initiatives** can too.

To put someone in charge of an initiative:

1. Open Community settings and select **Initiatives**.
2. On the initiative's row, select the box under **Project managers**.
3. Tick the person.

They become a Project Manager there, joining the initiative if they weren't in it. Unticking somebody moves them back to the Member role. Tick yourself to put an initiative in your own sidebar; unticking yourself, as an admin, takes you back out.

Each row's menu also has **Open settings**, **Archive** and **Delete**. Select **Archived** above the table to see archived initiatives, where the menu offers **Unarchive**. Below the table, **Rules for every initiative** sets tools and member permissions for all of them at once; see [Initiative roles](../sharing/initiative-roles.md#set-the-rules-for-every-initiative).

## Bring back something deleted { #trash-and-retention }

Anything deleted in the community goes to its trash first. Admins can restore anything there, and so can anyone whose custom role includes **Trash**. Everybody else finds their own deletions in their own trash.

1. Open Community settings and select **Trash**.
2. Find the thing in the list.
3. Select **Restore**.

It comes back exactly where it was. Restoring an initiative brings back everything that was deleted with it. To get rid of something for good, select **Delete now**, then **Delete forever**.

### Choose how long the trash keeps things

1. Open Community settings and select **Trash**.
2. Turn on the switch and type a number in **Delete permanently after … days**. Turn the switch off to keep everything until somebody deletes it by hand.
3. Select **Save**.

A new community keeps deleted things for 90 days. This is the setting that quietly saves somebody's entire afternoon about twice a year, so be generous with it. Nobody has ever regretted a long retention window at the moment they needed one.

## Export the whole community

Superadmins can download everything in the community at once.

1. Open Community settings and select **Data**.
2. Under **Export this community**, select **Export…**.
3. Choose **Importable backup**, for a file you can import here or on another server, or **Report à la carte**, to pick a readable format for each tool.
4. Choose what to include.
5. Select **Next**.
6. Select **Start export**.

The export runs in the background, and you get a notification when it's ready. Finished exports stay in the table on the **Data** tab, which says who took the last one and when, so you can download them again until they expire. A community can export everything once every couple of days; whoever runs your server sets the exact wait. A very large export is written to the server's export folder instead, and whoever runs the server can give you the file.

To put a backup back, or to bring in work from another app, see [Bringing work in from another tool](importing.md).

## Delete the community

Only a superadmin can delete a community. If you only want out, [leave it](communities.md#leave-a-community) instead; that removes just you.

1. Open Community settings and select **Danger zone**.
2. Select **Delete community**.
3. Type your password in **Confirm your password**, if your account has one.
4. Type the phrase it shows, `DELETE COMMUNITY` and the community's name in capitals.
5. Select **Delete**.

The community disappears for everyone in it straight away: initiatives, projects, tasks, files, members and settings. You get an email saying when it will be gone for good.

Until then it's kept, for 90 days unless whoever runs your server set another window, and they can restore it exactly as it was. If nobody's left who could run it, they can hand it to a new owner. So the 11pm decision is recoverable, as long as somebody notices in time. A restored community reconnects its installed plug-ins by itself.

The retyping is deliberate, and we're not sorry about it.

??? techspec "What deleting a community does"
    Deleting marks the community deleted and closes it to everyone at once. When the retention window runs out, its isolated database area and the database roles tied to it are removed, along with the shared records that connect people to it: memberships, invites, single sign-on mappings and access grants. Until then all of that is intact, which is what makes a restore a restore rather than a rebuild.
