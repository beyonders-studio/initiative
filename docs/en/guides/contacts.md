---
icon: lucide/book-user
---

# Contacts

**Contacts** is the address book for the people and places your work involves who aren't in your community: the client, the venue, the florist, the caterer, the guy with the bounce house.

Right now their details are probably in a task description from March, a screenshot of a business card, and the phone of somebody who is, at this exact moment, on vacation.

A contact is a person or an organization, and how to reach them. The work you do with them (the deposit task, the delivery event, the contract) stays on the tasks, events and files, linked to the contact.

## Turn on contacts

Contacts are off in a new initiative. An initiative manager switches them on:

1. Open **Initiative settings**.
2. On the **Details** tab, find **Tools**.
3. Turn on **Contacts**.

A **Contacts** tab appears in the initiative. Turning it off later hides the contacts without deleting anything.

## Add a contact

Adding contacts takes a role in the initiative that can create them. If you don't see **New contact**, ask an initiative manager.

1. Open the initiative's **Contacts** tab.
2. Select **New contact**.
3. Type the **Name**.
4. Choose **Person** or **Organization**.
5. Add how to reach them with **Add phone**, **Add email**, **Add address** and **Add website**, as many of each as they have.
6. Give each one a label if it helps: pick **Mobile**, **Work**, **Billing**, **Booking** and so on, or type your own, like "the number that actually gets answered".
7. For a person, pick their **Organization** if they work somewhere you already have.
8. Optional: open **Advanced options** to choose who can see them.
9. Select **New contact**.

Write an address the way it goes on an envelope, in any country's format, and a website with or without the `https://`. Everyone in the initiative can see a new contact unless you changed that in step 8.

Anything else you want to keep (a dietary note, a license number, whether the deposit's paid) goes in the initiative's [metadata](initiatives.md), like on any tool.

## Add someone who works at an organization

1. Open the organization.
2. Under **People**, select **Add person**.
3. Fill in their details as above.
4. Select **New contact**.

They show under **People** on the organization's page, and their own page says where they work. The venue lists its day-of coordinator, and the coordinator's card says which venue.

## Change how to reach someone

1. Open the contact.
2. In **How to reach them**, select **Edit**.
3. Change, add or remove details. The **×** beside a detail removes it.
4. Select **Save**.

Click the name at the top to rename them.

## Call, email or find a contact

On a contact's page, a phone number calls and an email address starts a new message, so on the phone app a contact is one tap from ringing. An address has a **Copy** button, for pasting into whatever you use to get lost.

To find a contact, search the **Contacts** tab, or open **Filters** and set **People or organizations** to **People** or **Organizations**.

## See where things stand with a contact

A contact's page shows the work linked to them under **Where things stand**: their **Open tasks**, what's **Coming up**, and their **Files**. The calls and notes go in the contact's comments.

None of that is typed onto the contact. It comes from the work: "Pay the florist's deposit" is a task, "Flowers arrive" is an event at 2:00, the contract is a file, and each is [linked](mentions-and-links.md#relations) to the florist. Tick the task off and it leaves their page by itself.

!!! tip "The deposit goes on the task, not the contact"
    It's tempting to type "deposit paid, arrives 2pm" onto the contact. Put it on the task and the event instead. The florist has one phone number but a different deposit at every wedding, and next June you'll be glad the card isn't covered in last year's.

## Add a task or an event for a contact

So the next thing you need to do about the florist starts from the florist:

1. Open the contact.
2. Under **Where things stand**, select **New task** or **New event**.
3. For a task, check the **Project** (**Change** picks another), type a **Title**, and select **Add task**.
4. For an event, fill it in as any [event](calendar.md#add-an-event) and select **Create Event**.

The new task or event is linked to the contact and shows on their page.

## Link a contact to someone with an account

Some contacts are also people in your community. The couple might be [guests](../sharing/guests.md) on their own wedding, for instance.

1. Open the contact.
2. In **Connections**, select **Add link**.
3. Select the **Members** tab.
4. Pick the person.
5. Pick how they relate and select **Add link**.

A contact never matches itself to an account by email address; you say which person it is.

## Mention a contact

Type `#` and the contact's name in a comment, description, document or wiki page to [link it](mentions-and-links.md). In a document, wiki page or post, a [smart chip](editor.md#smart-chips) can show their phone or email right in the sentence instead, so "call the venue" carries the venue's number, and clicking it calls them.

## Import contacts from a spreadsheet

Already have the vendor list in a spreadsheet or your phone's contacts? Save it as a CSV file (up to 20 MB) first.

1. Open the **Contacts** tab.
2. Open **More actions** (the **⋯**).
3. Select **Import contacts from CSV**.
4. Drop the CSV file on the box, or select **Choose a file**.
5. Under **What does each column hold?**, check what each column is: **Name**, **Person or organization**, **Email**, **Phone**, **Address**, **Website**, **Organization**, **Tags**, **Properties**, or **Leave out**. Most match themselves, including the columns a phone or email account exports.
6. For phone, email, address and website columns, pick where the label comes from.
7. Select **Start import**.

One column has to be the **Name**. Each row becomes a new contact, and a row that can't be read is left out and listed in the report afterward, rather than half-imported.

## Export contacts to a spreadsheet

Exporting is for whoever can also delete the contacts.

1. On the **Contacts** tab, open **More actions** › **Select items**.
2. Tick the contacts.
3. Select **Export**.
4. Pick **CSV**.

You get one row per contact, with columns like `Phone 1` and `Phone 1 label` when somebody has several, then their organization, tags, and a column per piece of metadata headed like `Metadata: Deposit paid`. Several tags or choices share one cell, one to a line. Import that file into another initiative, or back in here, and every column matches up by itself.

One contact also exports from its **Settings**, on the **Advanced** tab.

## Keep contacts for the whole community

Some contacts belong to one piece of work: the couple, their families, the venue's coordinator. Keep those in that initiative's **Contacts**.

Others turn up everywhere: the florist you use at every wedding, the supplier everyone orders from. Those go in the community's own contacts, from the **Community contacts** plug-in, which a community admin adds from the [marketplace](plugins-and-marketplace.md). It shows up in the sidebar's **Plug-ins** section.

- **Everyone in the community can look them up.** Guests see one only when it's shared with them.
- **Admins add them**, along with anyone given the **Community contacts** job in a [custom role](communities.md). Anyone given edit access to one contact can change that one.
- **Any initiative's work can link to them.** A task in the Smith wedding links to the florist in the community's contacts, and the florist's page shows the work linked to it that you can open, and nothing else.

## Move a contact into the community's contacts

Found somebody brilliant on one job? Moving them takes edit access to the contact and the **Community contacts** job (admins have it), and the plug-in has to be added.

1. Open the contact.
2. Open **More actions** (the **⋯**).
3. Select **Move to community contacts**.
4. Select **Move**.

Their links come with them. Metadata from the initiative stays behind, because it belonged to the initiative.

## Share a contact

Each contact has its own sharing (**Viewer**, **Editor**, **Owner**, or everyone in the initiative), on the **Access** tab of its **Settings**. So the couple can see the vendors they need and not the one you're quietly thinking of replacing. Contacts take tags, comments, connections and copies like every other [tool](tools.md).
