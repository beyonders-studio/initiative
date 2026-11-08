---
icon: lucide/hash
---

# Counters

A **counter** tracks a number that moves: tickets sold, seats left, money raised, points scored, laps run, cups of coffee the PTA board has had since September.

A number typed into a document is one person's number, and by Thursday it's wrong. A counter is everybody's. Tap it on your phone and the screen at the front of the room changes with it.

Counters live in **counter groups**, because they almost always come in sets: one per table at the fundraiser, one per team, one per donation jar. A group is the [tool](tools.md); the counters are what's inside it.

## Make a counter group

You need a role in the initiative that can create counters. If there's no button, ask one of the initiative's managers.

1. Open the initiative and select its **Counters** tab.
2. Select **Create Counter Group**. (On a phone, it's the **+** at the bottom of the screen.)
3. Type a **Name**, and a description if you like.
4. To change who can see it, open **Advanced options**.
5. Select **Create Counter Group**.

The group opens, ready for its first counter. In the list, each group's card shows its first few counters, so you can check the score without opening anything.

## Add a counter

You need edit access to the group.

1. Open the group.
2. Select **Add Counter**.
3. Type a **Name** and pick a **Color**, or keep the one it suggests.
4. Set a **Min** and **Max** if the number has bounds. Seats can't go below zero, and the gym only holds 300.
5. Set the **Step**: how much one tap moves it. Set it to 5 and each tap is five.
6. Set the **Initial value**, where the counter starts and where a reset sends it back to.
7. Pick a **View mode**: **Number**, **Progress bar** or **Segmented clock**.
8. Select **Add Counter**.

The new counter starts at its initial value. Counters take decimals, so a fundraising total in dollars and cents works as well as a headcount.

### Pick a view mode

- **Number**, when the value is the message: a total, a tally, a score.
- **Progress bar**, when the value only means something against a target. $2,400 raised is a fact; $2,400 of $3,000 is a story.
- **Segmented clock**, when you're counting down a handful of things: rounds, doses, lives, attempts.

A progress bar and a segmented clock both need a **Min** and a **Max**, so they stay grayed out until both are set.

!!! screenshot "A counter group"
    **Show:** a counter group with three or four counters in rows, one of each view mode, and the strip at the top with **Add Counter**, **Sort** and **Reset All**.

    Save as `en/images/counters/counter-group.png`, then replace this box with:
    `![A counter group with a number, a progress bar and a segmented clock](../images/counters/counter-group.png)`

## Change the count

Tap **+** (**Increment**) or **−** (**Decrement**) beside a counter. Each tap moves it by its step, and the buttons gray out at the min and max.

To set an exact number, tap the number itself and type. It saves when you press ++enter++, tap away, or stop typing for a moment.

The count never goes past the counter's min or max, however it's changed. Viewers see the count change but can't change it themselves; that takes edit access.

## Show a counter full screen

Counters usually get read from the back of a school gym by somebody who left their glasses in the car. Full screen is for them.

1. Open the counter's **More actions** menu (the **⋮** on its row).
2. Select **Open full screen**.

The counter fills the screen in its own color, with big **+** and **−** buttons. When the group has more than one counter, **Previous counter** and **Next counter** move between them (so does swiping sideways), and the position ("2 / 5") shows which one you're on. **Exit full screen**, the **X** at the top, takes you back. Anyone who can see the group can open it, which makes it handy on a projector or a tablet propped up by the door.

## Edit or remove a counter

1. Open the counter's **More actions** menu.
2. Select **Edit Counter**.
3. Change what you need. Each field saves as you change it.

To remove one, select **Remove Counter** in the same menu, then confirm. Changing a min or max pulls the count (and the initial value) back inside the new bounds if it was outside them.

How the counter's dialog is laid out is the group's **Counter detail** [layout](layouts.md), which you can change under **Settings** › **Layouts**.

## Reset counters

- **One counter:** open its **More actions** menu and select **Reset**. It goes back to its initial value.
- **The whole group:** select **Reset All** in the strip at the top of the group, then confirm. It's the button for between sessions.

## Duplicate a counter

1. Open the counter's **More actions** menu.
2. Select **Duplicate**.

The copy lands at the end of the group with "(Copy)" after its name, keeping the count, the bounds, the step, the color and the view mode. It's for when the second team turns up.

## Arrange the group

- **Reorder** counters by dragging each by its handle (**Drag to reorder**).
- **Sort** them by **Name (A→Z)**, **Name (Z→A)**, **Count (low→high)** or **Count (high→low)**. Sorting rearranges the saved order for everyone, so it's a one-time tidy rather than a view.
- **Switch to grid view** or **Switch to row view** with the button in the strip. That choice is yours alone and only changes your screen.

**Add Counter**, **Sort** and **Reset All** are only there for people with edit access.

## Settings, sharing and the rest

A counter group's **Settings** has **Details**, **Access**, **Layouts** and **Advanced**, and the group shares, tags, archives, exports, duplicates and goes to the trash like every other tool. See [Tools](tools.md). A group can be tagged; the counters inside it can't.

A [dashboard](dashboards.md) can show counters too, beside everything else.
