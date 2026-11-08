---
icon: lucide/book-user
---

# Contacts

**Contacts** is the address book for the people and places your work involves but who aren't in your community. The client. The venue. The florist, the caterer, the man with the marquee.

Right now their details are probably in a task description from March, a screenshot of a business card, and somebody's phone. Somebody who is, at this exact moment, on holiday.

## A contact

A contact is a **person** or an **organization**, and how to reach them:

| Field | Notes |
|---|---|
| **Phone** | As many as they have, each with a label: Mobile, Office, the number that actually gets answered. |
| **Email** | The same, so Bookings and Billing can both live on one card. |
| **Address** | Written the way it goes on an envelope, in any country's format. |
| **Website** | Typed without the `https://` is fine. |

Phone numbers call and emails open a new message, so on the phone app a contact is one tap from ringing. Addresses have a **Copy** button, for pasting into whatever you use to get lost.

Anything else you want to keep (a dietary note, a pricing tier, a licence number) goes in the initiative's [metadata](initiatives.md#metadata), like on any tool.

### People at an organization

Pick an **Organization** when you add a person, and they show up under **People** on that organization's page. The venue lists its day-of coordinator; the coordinator's card says where they work. **Add person** on an organization's page does both at once.

## Where things stand with them

A contact's page shows what's linked to it: its **Open tasks**, what's **Coming up**, and its **Files**. Its comments are where the calls and notes go.

None of that is typed onto the contact. It comes from the work. "Pay the florist's deposit" is a task, "Flowers arrive" is an event at 2:00, the contract is a file, and each is [linked](mentions-and-links.md#connections) to the florist. Tick the task off and it leaves their page on its own.

**New task** and **New event** on a contact make one already linked to them, so the next thing you need to do about the florist starts from the florist.

!!! tip "The deposit goes on the task, not the contact"
    It is tempting to type "deposit paid, arrives 2pm" into the contact. Put it on the task and the event instead. The florist has one phone number but a different deposit at every wedding, and next June you'll be glad the card isn't covered in last year's.

## The community's contacts

Some contacts belong to one piece of work: the couple, their family, the venue's day-of contact. Keep those in that initiative's **Contacts**.

Others turn up everywhere. The florist you use at every wedding. The supplier everyone orders from. Those go in the community's own contacts, from the **Community contacts** plug-in, which a community admin adds from the [marketplace](plugins-and-marketplace.md). It shows up in the sidebar's Plug-ins section.

- **Everyone in the community can look them up.** Guests see one only when it's shared with them.
- **Admins add them**, along with anyone given the **Community contacts** job in a [custom role](communities.md#custom-roles). Anyone given edit access to one contact can change that one.
- **Any initiative's work can link to them.** A task in the Smith wedding links to the florist in the community's contacts. The florist's page shows the work linked to it that you can open, and nothing else.

Found somebody brilliant on one job? **Move to community contacts**, in the contact's menu, moves them across. Their links come too. Anything filled in from that initiative's own metadata stays behind, because it belonged to the initiative.

## People with accounts

Some contacts are also people in your community. The couple might be [guests](../sharing/guests.md) on their own wedding, for instance. Link the contact to them like anything else: **Add link** → **Members**. A contact never matches itself to an account by email.

## Mentioning a contact

Type `#` and the contact's name in a description, document or wiki page to [link it](mentions-and-links.md). In a document or wiki page, a [smart chip](files.md#smart-chips) can show their **phone** or **email** in the sentence instead, so "ring the venue" carries the venue's number, and tapping it rings them.

## Getting a list in and out

Already have the vendor list in a spreadsheet? **More actions** → **Import contacts from CSV** on the Contacts tab takes the file. Match each column to a field, a label, the organization, tags or metadata. Most columns match themselves, including the ones a phone or email account exports, and any row that doesn't fit is listed afterwards rather than half-imported.

Export writes a CSV the same way, one row per contact, with columns like `Phone 1` and `Phone 1 label` when somebody has several. Several tags, or several choices, share one cell, one to a line. Metadata columns say so in the header, like `Metadata: Deposit paid`. Import that file into another initiative, or back in here, and every column matches up on its own.

## Sharing and comments

Each contact has its own sharing — **Viewer**, **Editor**, **Owner**, or everyone in the initiative — so the couple can see the vendors they need and not the one you're quietly considering replacing. Contacts take tags, comments, connections and copies like every other tool. See [Tools](tools.md).

## Related

- [Mentions & links](mentions-and-links.md) — linking a contact to the work.
- [Plug-ins & the marketplace](plugins-and-marketplace.md) — where the community's contacts come from.
- [Tools](tools.md) — what every tool shares.
