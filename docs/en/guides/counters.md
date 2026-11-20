---
icon: lucide/hash
---

# Counters

A **counter** tracks a number that moves: tickets sold, seats left, money raised, points scored, laps run, cups of coffee the PTA board has had since September.

A number typed into a document is one person's number, and by Thursday it's wrong. A counter is everybody's. There's one of it, in one place, and whoever opens it sees the same number.

Counters live in **counter groups**, because they almost always come in sets: one per table at the fundraiser, one per team, one per donation jar. A group is the [tool](tools.md); the counters are what's inside it.

## Add Counters to your community

Counters is a free [plug-in](plugins-and-marketplace.md) that ships with Initiative. Your community's [superadmin](running-a-community.md#why-superadmin-is-separate) adds it from the community's marketplace and picks the initiatives it goes in. After that it works like any other tool there: each initiative [switches it on or off](tools.md#turn-a-tool-on-or-off-for-an-initiative), and each role says who can see counter groups and who can make them. See [Use a tool a plug-in added](plugins-and-marketplace.md#use-a-tool-a-plug-in-added).

A community that used counters before they became a plug-in already has it, in the initiatives that used them, with every group and counter where it was.

## Make a counter group

You need a role in the initiative that can create counter groups. If there's no **New Counter group** button, ask one of the initiative's managers.

1. Open the initiative and select its **Counters** tab.
2. Select **New Counter group**. (On a phone, it's the **+** at the bottom of the screen.)
3. Give it a name, and a **Description** and **Tags** if you like.
4. Select **New Counter group** at the bottom of the dialog.

The group opens on its own page, and you're its owner. Its counters go under **Counter**, further down the page.

## Add a counter

You need edit access to the group.

1. Open the group.
2. Under **Counter**, select **New Counter**.
3. Give it a name.
4. Pick a **Color**, or leave it empty and one gets picked for you.
5. Set a **Min** and **Max** if the number has bounds. Seats can't go below zero, and the gym only holds 300.
6. Set the **Step**: how much one tap moves it. Set it to 5 and each tap is five.
7. Set the **Initial value**, where the counter starts and where a reset sends it back to.
8. Pick a **View mode**: **Number**, **Progress bar** or **Segmented clock**.
9. Select **New Counter**.

The counter's own page opens. It starts at its initial value, unless you set the **Count** in the dialog yourself. Counters take decimals, so a fundraising total in dollars and cents works as well as a headcount.

The step has to be more than zero, and the min can't be more than the max. Everything else is up to you.

### Pick a view mode

The view mode is how a counter is drawn where counters are listed: on its group's page, and on the group's card on the **Counters** tab.

- **Number**, when the value is the message: a total, a tally, a score.
- **Progress bar**, when the value only means something against a target. $2,400 raised is a fact; $2,400 of $3,000 is a story.
- **Segmented clock**, when you're counting down a handful of things: rounds, doses, lives, attempts. Each step fills one slice.

A progress bar and a segmented clock both need a **Min** and a **Max**. Without both, the counter shows as a number.

![A counter group's counters: two as progress bars, one as a number and one as a segmented clock, each between its step buttons](../images/counters/counter-group.webp#only-light)
![A counter group's counters: two as progress bars, one as a number and one as a segmented clock, each between its step buttons](../images/counters/counter-group.dark.webp#only-dark)

## Change the count

Wherever a counter shows, people with edit access to its group get a **−** and a **+** beside it. Each tap moves it by its step, and you don't have to open anything first:

- **On the Counters tab**, each group's card shows its first four counters.
- **On the group's page**, every counter is listed under **Counter**.
- **On the counter's own page**, the buttons sit either side of **Count**.

To set an exact number, open the counter and type it into the **Count** box. It saves when you press ++enter++, tap away, or stop typing for a moment.

The count never goes past the counter's min or max, however it's changed, and the button that would take it there grays out. Anyone who can only view the group sees the number without the buttons.

## Show a counter full screen

Counters usually get read from the back of a school gym by somebody who left their glasses in the car. Full screen is for them.

1. Open the counter.
2. Select the arrows at the end of the **Count** row (**Open Count full screen**).

The number fills the screen, with a big **−** and **+** across the bottom. The menu at the top right resets it, and **Exit full screen** (the **X**) takes you back. It's handy on a projector, or on a tablet propped up by the door.

## Change a counter

Open the counter. Its name is at the top, and its **Color**, **Min**, **Max**, **Step**, **Initial value** and **View mode** are down the side. Select the name to rename it. Every change saves as you make it.

Changing a min or a max pulls the count back inside the new bounds if it was outside them.

## Reset counters

- **One counter:** open it and select the curved arrow beside the count (**Reset Count**). **Reset**, in the counter's **Actions** menu (the **⋯** beside its name), does the same.
- **The whole group:** open the group, open **Actions** (the **⋯** beside its name), select **Reset All**, and confirm with **Reset All**. It's the button for between sessions.

A reset puts a counter back to its initial value, or to the nearer bound if the initial value is outside them.

## Sort and lay out counters

The **Counters** tab, and the **Counter** list on each group's page, have the same controls along the top:

- **Active** and **Archived** switch between what's in use and what's been put away.
- **Grid** and **Table** switch between cards and rows. A group's table shows each counter's count, min, max and step.
- **Choose a preset**, on a group's counters, sorts them by **Name (A→Z)**, **Name (Z→A)**, **Count (low→high)** or **Count (high→low)**.

Your view and preset are yours alone, and they change nobody else's screen.

What a card shows, which columns a table has and how a counter's page is arranged are all [layouts](layouts.md). Whoever can change them finds **Layouts** in **More actions** (the **…**): on the **Counters** tab for the groups, and beside a group's counters for the counters in it.

## Share, archive or delete a group

A counter group's **Actions** menu (the **⋯** beside its name) holds the rest:

- **Access settings** decides who in the initiative can see the group and who can change it. Its counters go wherever it goes. See [Sharing](../sharing/sharing-projects-and-files.md).
- **Archive** moves it under **Archived** on the **Counters** tab, and **Unarchive** in the same menu brings it back.
- **Delete** sends it, counters and all, to the trash. You can restore it from [My Settings › Trash](../account/profile-and-preferences.md#trash) until the community's retention period runs out.

A counter's own **Actions** menu has **Archive** and **Delete** too, for one counter at a time.

To copy a group, or to tag, share or delete several at once, open **More actions** on the **Counters** tab and select **Select items**. **Duplicate** copies each group you picked with every counter in it, with "(Copy)" after its name. See [Change several at once](tools.md#change-several-at-once).

## Comments, tags and links

A counter group has **Tags** under its description and a **Comments** thread further down its page, like every other tool, so the conversation about the scoreboard happens on the scoreboard.

Groups and counters both have **Connections**, for linking them to tasks, files and anything else in the initiative. See [Mentions & links](mentions-and-links.md#connections). A task that's **blocked by** a counter waits until the count reaches its max, which is what "we can't book the bus until 40 kids have signed up" looks like written down. See [See what's blocking a task](mentions-and-links.md#see-whats-blocking-a-task).
