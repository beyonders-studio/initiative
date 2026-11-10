---
icon: lucide/shield-user
---

# Initiative roles

Everyone in an [initiative](../guides/initiatives.md) holds one **role**: a named set of permissions, which is to say the things that role is allowed to do. A role decides which of the initiative's tools somebody can see, and whether they can make new things in them. You describe a kind of person once, like "Volunteer" or "Board member", and hand it out, instead of setting everything person by person.

Roles answer "what can this kind of person do here?" Sharing answers a different question, "who can open this one project?", and has [its own page](sharing-projects-and-files.md). Both apply at once. A role can let somebody make files in general, while one particular file is still only open to the three people it was shared with, and the two don't fight.

## The built-in roles { #the-two-built-in-roles }

Every initiative comes with three roles that can't be deleted:

| Role | What it's for |
|---|---|
| **Moderator** | Can use every tool, and can open, edit and share every item in the initiative however it's shared. That reach is called **Full access**. Moderators also run the initiative like a Project Manager, and they get its [Moderation](../guides/moderation.md) page. |
| **Project Manager** | Runs the initiative: its members, its roles and its settings. Can see and make things in every tool. Which individual items they can open is still decided by how each one is shared. |
| **Member** | Where everybody else starts. What members can do is yours to set. |

Moderators and Project Managers are the initiative's **managers**. Their tool permissions are fixed at "everything", so their cards on the **Roles** tab just say what they are. You can rename any role, built-in ones included, with the pencil on its card.

Only Moderator has Full access, and no other role can be given it. Putting somebody on the Moderator role, or taking them off it, is a community admin's job; Project Managers handle every other role. Community admins themselves always hold Moderator in an initiative, because they can already open everything in the community.

!!! warning "Moderators see everything"
    Because Moderator reaches every item however it's shared, anything kept private to a few people is still visible to every Moderator. Give it to the people who genuinely need the whole picture, not as a thank-you for being helpful, and not because somebody's been around a long time and it felt rude not to.

## What a role can allow

For each tool, a role has two switches:

| Switch | Lets them |
|---|---|
| **View** | See the tool in the initiative, and the things in it that are shared with them. |
| **Create** | Make new things in the tool. |

The tools are **Projects**, **Files**, **Events** (the calendar), **Counters**, **Dashboards**, **Posts**, **Wikis** and **Contacts**. Turning on **Create** turns on **View** too, and turning off **View** turns off **Create**, since making something you can't see isn't a state worth having.

Each role also has **Run dashboards as Initiative**, which lets its holders set a dashboard to show every row in the initiative to everyone who opens it, whatever each viewer could open on their own. It starts off for everyone but managers.

Tools the initiative has switched off are listed under **Turned off for this initiative**. You can still set them, so turning the tool back on doesn't mean redoing your roles, but they grant nothing until it's on again.

So a "Volunteer" might view projects and files and create nothing, while a "Coordinator" creates everything.

### Plug-ins on a role { #plug-ins-on-a-role }

Each [plug-in](../guides/plugins-and-marketplace.md) that works in the initiative adds switches of its own to every role: **Use** for the plug-in itself, and any part it lets you hand out separately, such as seeing prices. A role starts the way the plug-in suggests, which for most is off. Managers and community admins hold every one, so the manager cards don't list them. Turn one on for a role to let its holders open the plug-in's page, see its fields and run its actions in this initiative.

## Set what members can do

The initiative's managers and community admins can change roles.

1. Open the initiative's **Initiative settings** and select **Roles**.
2. On the **Member** card, turn **View** and **Create** on or off for each tool, and each plug-in's switches below them.

Each switch saves as you flip it, and it applies to everyone on the Member role straight away. A switch showing **On** or **Off** with a lock was set by your community for every initiative (see [Set the rules for every initiative](#set-the-rules-for-every-initiative)).

![The Roles tab of Initiative settings, with the Moderator and Project Manager cards, the Member card's View and Create switches for each tool, and Add custom role](../images/sharing/role-permissions.webp#only-light)
![The Roles tab of Initiative settings, with the Moderator and Project Manager cards, the Member card's View and Create switches for each tool, and Add custom role](../images/sharing/role-permissions.dark.webp#only-dark)

## Make your own role

The initiative's managers and community admins can add roles, unless your community keeps initiatives to the built-in ones. Then the **Roles** tab says so instead of offering the button.

1. Open **Initiative settings** and select **Roles**.
2. Select **Add custom role**.
3. Type a **Display name**, the name people will see. The **Internal name** fills itself in.
4. Select **Create role**.
5. On the new role's card, turn **View** and **Create** on for what it should allow.

It's ready to hand out straight away. Name roles after people, the way your group talks about itself. "Volunteer" is friendlier and clearer than "View-only contributor", and nobody has ever introduced themselves at a committee meeting as a view-only contributor.

## Rename or delete a role

The initiative's managers and community admins can rename and delete roles.

To rename one:

1. Open **Initiative settings** and select **Roles**.
2. Select the pencil on the role's card.
3. Change the **Display name**.
4. Select **Save**.

To delete one you made:

1. Move everybody off it first. A role somebody holds can't be deleted.
2. Select the trash can on the role's card.
3. Select **Delete**.

## Give someone a role

The initiative's managers and community admins pick a role when they [add someone](../guides/initiatives.md#add-someone-to-an-initiative), and can change it later.

1. Open **Initiative settings** and select **Members**.
2. In the person's **Role**, choose the new role.

The change applies immediately, with no signing out and back in. Two limits apply: only a community admin can move somebody onto Moderator or off it, and an initiative always keeps at least one manager.

## Set the rules for every initiative

Some communities want every initiative to work the same way: posts switched on everywhere, say, or members never making dashboards. Community admins can set that once for all of them, including initiatives made later.

1. Open **Community settings** and select **Initiatives**.
2. Under **Rules for every initiative**, select **Add a rule**.
3. Choose the **Tool or plug-in**.
4. For a tool, answer **Is … turned on?**: **Each initiative decides**, **On in every initiative** or **Off in every initiative**. Then answer **Can members view …?**: **Each initiative decides**, **Yes, in every initiative** or **No, only managers**, and **Can members create …?** the same way.
5. For a plug-in, answer **Do members have …?** the same way, for each switch it adds.
6. Read **Who it changes today**, which lists the initiatives the rule would change.
7. Select **Save rule**.

Every initiative takes the rule at once, archived ones included. Their managers see the switches set the way the community said, with a lock, and can't change them. To change a rule later, select **Edit** beside it. The trash can beside it removes the rule, which hands those questions back to each initiative, with whatever each one had set before.

The same card has **Managers can add roles**. Turned off, no initiative can add roles beyond Moderator, Project Manager and Member, and any role an initiative already added can do no more than members, so what the community said still holds.
