---
icon: lucide/file-up
---

# Bringing work in from another tool

Coming from somewhere else? You don't have to retype four years of tasks by hand. One import window brings in work from another app, or puts back a backup you exported from Initiative.

Importing is a superadmin's job, from the **Data** tab of Community settings, because it can add a lot to a community at once. Everything arrives as something new, and nothing already in your community is changed, so a first attempt you hate costs you one delete.

Bringing a single exported file into one tool, like a spreadsheet of contacts, is a smaller job that lives on that tool's own page (for contacts, see [Contacts](contacts.md)).

## Import a project from another task app

The import reads exports from **Todoist**, **TickTick** and **Vikunja**. Export your work there first; the import window tells you where that app keeps its export.

1. Open **Community settings** and select **Data**.
2. Select **Import…**.
3. Under **Where is this coming from?**, choose the app.
4. Choose your export file, or drop it on the box.
5. In **What to import**, choose the list or project from the file.
6. Type a name in **Name the project**.
7. Choose the **Initiative** it lands in.
8. Select **Start import**.
9. If the window asks **Who are these people here?**, pick who each person in the file is here. Handles that match a member are filled in already; leave one blank and their name stays as plain text.
10. Select **Start import** again.

The import runs in the background, so you can close the window. You get a notification when it's done, and the report stays on the **Data** tab. Each list or project arrives as a new project with its dates, priorities, tags, assignees, checklists, comments and when things were finished. Its own sections or lists become your statuses, so nothing has to be mapped onto columns by hand. Anyone assigned or named in it is added to the initiative, if you manage it, and gets access to what came in.

!!! note "Todoist leaves out what you finished"
    Todoist's export holds outstanding work only, so completed tasks won't come across. The import window says so before you upload, rather than after.

## Import from Jira and Confluence

Jira and Confluence have no file to drop in, so the import reads your Atlassian site directly: Jira projects, Confluence spaces, or both in one go. You'll need an API token from your Atlassian account; the import window links to where you make one.

1. Open **Community settings** and select **Data**.
2. Select **Import…**.
3. Choose **Jira & Confluence**.
4. Type your **Site address**, **Your Atlassian email** and **API token**.
5. Select **Connect**.
6. Tick the **Projects** and **Spaces** to bring over.
7. Choose the initiative they land in. Only initiatives you can add all of it to are listed.
8. Tick **Bring comments** and **Bring attachments** if you want them.
9. Select **Start reading**.
10. Wait while it reads. A big project takes a few minutes, and you can close the window: opening the import again picks up where it was.
11. Check what it found. Nothing has been written yet. Untick any Jira fields you don't want added as metadata.
12. Select **Next**. If nobody in it needs matching, the button says **Start import** instead, and selecting it finishes the job.
13. Under **Who are these people here?**, check who each person is here. Somebody who's in both Jira and Confluence is asked about once.
14. Select **Start import**.

The token is used only to read what you picked, and it's deleted as soon as it's been read. The review lists everything coming across, and just as plainly, anything that won't: a project the token can't read, a sprint that never started, the macro somebody installed in 2017 and never mentioned again.

**Each Jira project** becomes a new project here, with its columns, fields, links between issues, and sub-tasks under their parents. Each sprint becomes an event on a calendar named after its board, so an initiative without calendars gets everything except the sprints, and the review says so first. Pictures sit where the issue showed them, and other attached files land in Files, attached to their task.

**Each Confluence space** becomes a [wiki](wikis.md) with its page tree kept as it was: the home page is the home page, children sit under their parents, and labels become tags. A folder, or a parent page that only ever existed to hold its children, becomes a page listing what's inside it. Links between pages point at the imported pages. Panels become callouts, status lozenges become statuses in their own colors, and a decision log becomes a checklist ticked where things were decided. Pictures sit where the page showed them, and other attached files land in Files, in the wiki under the page they were attached to, so the spreadsheet everyone was told to "just check the attachment" for is one click away. Comments come too, footer and inline, with replies under what they answer; an inline comment marked resolved stays behind. Attachments need Files switched on in the initiative.

Bring a project and its space over together and they arrive joined up. A page that mentions an issue points at the task it became, with a [smart chip](mentions-and-links.md) showing that task's status as it is today. An issue that links to a page points at the wiki page. A page that mentions an issue from an earlier Jira import is joined up too.

### Import a Confluence space from an HTML export

No token to hand, or a Confluence your server can't reach, like one on the office network? Export the space instead. In Confluence, that's **Space settings**, **Export space**, **HTML**.

1. Open **Community settings** and select **Data**.
2. Select **Import…**.
3. Choose **Jira & Confluence**.
4. Select **Have an HTML export of a Confluence space instead? Upload it**.
5. Choose the export .zip.
6. Choose the **Initiative** it lands in.
7. Tick **Bring attachments** if you want them.
8. Select **Start reading**.
9. Carry on from checking what it found, as above.

It's read the same way and you get the same review, though comments stay behind, and people are matched by the names the export prints.

## Put back an Initiative backup

A backup is the file Initiative makes when you export a community or an initiative as an **Importable backup** (see [Export the whole community](running-a-community.md#export-the-whole-community)). It works on this server or another one, as long as it was made on Initiative 0.78 or later: an older one restores on 0.78 first, and a backup made there then restores here.

1. Open **Community settings** and select **Data**.
2. Select **Import…**.
3. Choose **Initiative backup**.
4. Choose the backup's .zip file.
5. Check what's in it, then select **Upload backup**.
6. Read **Review what will be imported**: each initiative in the backup and the name it will arrive under.
7. If the button says **Next**, select it and check who each person in the backup is here.
8. Select **Start import**.

Every initiative in the backup is created fresh, beside what you already have; nothing existing is changed. The import runs in the background, and the report says how many things came across, which failed and which were skipped.
