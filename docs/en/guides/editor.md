---
icon: lucide/pen-line
---

# Writing & formatting

Text documents, wiki pages and posts are all written in the same editor, so once you've written one you can write all three. A post gets a shorter toolbar, since a notice is a place to say something rather than typeset it, but the `/` menu has everything in all three.

Writing something in the editor needs edit access to it. Everyone else reads the page, and the toolbar doesn't appear.

A text document or wiki page saves itself, and other people's changes appear as they type ([Files](files.md#work-on-a-file-with-other-people-at-the-same-time) has the details). A post saves when you post it, or when you select **Save** after editing it.

## Format text

Select the words, then pick from the toolbar along the top:

- **Undo** and **Redo**.
- The block type: **Paragraph**, **Heading 1**, **Heading 2**, **Heading 3**, **Numbered list**, **Bulleted list**, **Checklist**, **Code block** or **Blockquote**.
- **Font size**.
- **Bold**, **Italic**, **Underline**, **Strikethrough**, **Subscript** and **Superscript**.
- **Insert link**.
- **Clear Formatting**.
- **Text Color** and **Background**.
- **Align**, with **Indent** and **Outdent**.

When the editor is narrow, whatever doesn't fit moves into **More formatting** at the end of the toolbar. Selecting words also brings up a small toolbar right beside them.

A post's toolbar keeps undo, the block type, **Bold**, **Italic**, **Underline**, **Strikethrough**, **Insert link** and **Insert**, with **Clear Formatting** and **Align** under **More formatting**.

Markdown shortcuts work as you type: `#` and a space starts a heading, `-` and a space a bulleted list, `1.` and a space a numbered list, `>` and a space a quote, and `**` around a word makes it bold. A colon and a word (`:tada`) offers emoji.

## Insert anything with /

Type `/` at the start of a line, or anywhere, and keep typing to narrow the list. Pick an entry with the mouse or ++enter++.

The list holds paragraphs, headings, tables, lists, quotes, callouts, code, a divider, YouTube videos and tweets, pictures, drawings, diagrams, statuses, smart chips, embeds, columns and alignment. Type `3x4` and it offers a table that size.

The toolbar's **Insert** menu has the same things for people who'd rather click: **Horizontal rule**, **Image**, **Table**, **Status**, **Drawing**, **Callout**, **Columns Layout**, the video and tweet embeds, **Smart chip** and **Embed**.

## Add a callout

A callout is a colored panel for the thing nobody should miss. Unlike a quote, it can hold anything: lists, a table, code.

1. Type `/callout`.
2. Pick the kind: **Info**, **Note**, **Tip**, **Success**, **Warning** or **Error**.
3. Type inside it.

Click the callout's icon to change its kind, or choose **Remove callout** to take the panel away and keep the words. The arrow in its corner folds it down to its first line (**Collapse callout**), so put a title on that line and a long aside becomes one line until somebody wants it. Folding is saved with the page for everyone.

## Add a status

A status is a word in a colored pill, set by hand: *Done*, *Blocked*, *Waiting on the HOA*.

1. Type `/status` and pick **Status**.
2. Click the new pill.
3. Type the **Status text** and pick a color (**Grey**, **Blue**, **Green**, **Yellow**, **Red** or **Purple**).

**Change status** on the pill changes it later, and **Remove status** takes it out. For a status that keeps itself up to date, use a [smart chip](#smart-chips).

## Add a table

1. Type `/table` and pick **Table**, or choose **Insert** › **Table**.
2. Fill in **Number of rows** and **Number of columns**.
3. Confirm.

Click in a cell and open **Table actions** (the small arrow in the cell) to **Insert row above**, **Insert row below**, **Insert column left**, **Insert column right**, **Delete row**, **Delete column**, **Delete table**, **Toggle header row** or **Toggle header column**.

To merge cells, drag across them, open **Table actions** and choose **Merge cells**. **Unmerge cells** splits them back. It's how you get the heading over three columns and the row label that runs down two.

## Add a picture

1. Choose **Insert** › **Image**, or type `/image`.
2. Pick where it comes from: **URL** for a web address, **File** to upload from your device, or **Files** for a picture already in your initiative's Files.
3. Type **Alt text**, a short description for someone who can't see it.
4. Confirm.

You can also paste a picture, or drag one onto the page. Then:

- Drag the handles on a selected picture to resize it.
- **Add Caption** puts a caption under it.
- Click a picture while reading to see it full size, and zoom with a pinch, a double-tap, ++ctrl++ and the scroll wheel, or the buttons along the top.

A picture from **Files** goes in as the file is right now. Upload a newer version of the logo tomorrow and this page keeps today's, which is usually what you want for the minutes. Pictures in a document belong to its initiative, and anyone who can read the document sees them, whoever the original file is shared with.

## Add a drawing

A drawing is a small whiteboard inside the page.

1. Type `/drawing` and pick **Drawing**.
2. Draw.
3. Select **Save drawing**.

It sits on the page as a picture. Select it and choose **Edit drawing** to open it again.

## Draw a diagram from text

Flowcharts, sequence diagrams and the like can be written as text in [Mermaid](https://mermaid.js.org/), and the editor draws them as you type.

1. Type `/diagram` and pick **Diagram**.
2. Write the diagram's text in the block.

Readers see the picture without the text in their way. Any code block set to Mermaid in **Select language** is drawn the same way, and a mistake shows as "This diagram has a mistake in it" with what's wrong.

## Lay text out in columns

1. Choose **Insert** › **Columns Layout**.
2. Pick a layout, from **2 columns (equal width)** to **4 columns (equal width)**.
3. Confirm.

Type into each column like a small page of its own.

## Embed a YouTube video or a tweet

1. Type `/` and pick **Embed YouTube Video** or **Embed Tweet**.
2. Paste the link.

Pasting a YouTube or X link on its own line offers to embed it too.

## Show a task's status, a date or a number with a smart chip { #smart-chips }

A link tells you something exists. A smart chip tells you what it's doing right now, and keeps telling you without anyone maintaining it. Move a task to Done and every chip pointing at it turns green, in every file that mentions it, with nobody editing a word, so last month's meeting notes are accurate today without anybody touching them.

1. Type `/` and the fact you want, like `/task status`, and pick it.
2. Pick the thing from the list. It opens on what you've worked on most recently, so there's often nothing to type.

From the toolbar it's the other way round: **Insert** › **Smart chip**, pick the thing, then answer **Which fact should the chip show?**

| Smart chip | Shows |
|---|---|
| **Task status** | The column it's in, in that column's color |
| **Task assignee** | Who's holding it |
| **Task due date** | When it's due, in red once that's passed unless it's done |
| **Task priority** | How urgent somebody said it was |
| **Task checkbox** | A box and the task's name. Tick it and the task is done |
| **Project progress** | Tasks done out of all of them, like **2 / 5** |
| **Counter value** | The current number, against its target if it has one |
| **Event date** | When it happens, dimmed once it has |
| **Contact phone** | Their first phone number. Click to call |
| **Contact email** | Their first email address. Click to write |

Hover a chip to see what the thing is called and what kind of thing it is, and click it to go there.

The task checkbox is the one chip you can use. Only people who can edit the task get a working box; everyone else just sees it ticked or not. An ordinary checklist ticks a line on this page and nothing else, which is right for an attendance list. When the line is real work, use a task checkbox, and ticking it in the minutes ticks it on the board too.

Chips work in text documents, wiki pages and posts. They point only at things in the page's own initiative.

!!! note "What other people see"
    A chip shows what the reader can see. Somebody who can't open the task sees the name it had when the chip went in, and nothing about its state. An exported PDF or Word file shows that name too, since a printed page can't keep itself up to date.

## Show something in full with an embed { #embeds }

A chip shows one fact. An embed shows the whole thing in a panel of its own: its name and the description somebody wrote for it (a task's notes, what a calendar is for). Embed a text document or a wiki page and you get the page itself, read-only, in a scrolling pane. A spreadsheet, a whiteboard or an upload shows its name.

1. Type `![[` and start typing the thing's name.
2. Pick it.

Or choose **Insert** › **Embed**, find the thing under **One thing**, and select **Embed**.

Already have a `#` link to it? Hover the link and choose **Show in full**. **Show as a link**, in the embed's corner, turns it back.

To show tasks matching a filter instead of one thing:

1. Choose **Insert** › **Embed**.
2. Select **Tasks matching a filter**.
3. Type a **Label**, like "Open launch tasks".
4. Under **From**, pick one project or **Every project in this initiative**.
5. Set the filter.
6. Pick how to show them: **List**, **Table** or **Count**.
7. Select **Embed**.

A page that says "Open launch tasks: 7" means it, today and next week. For one thing, **Embed settings** changes **Show as** between **Card** (everything) and **Chosen details** (just the fields you pick).

Embeds read live, like chips: rewrite the task's description and every page embedding it says the new thing. The arrow in an embed's corner folds it to its name, and that's saved with the page; a reader can still open it for themselves. An embedded page's own embeds show as names only, so two pages that embed each other don't go on forever.

## Jump around a long document

**Contents**, above a text document, lists its headings, nested the way you wrote them. Pick one and the page scrolls there, and the list marks where you are as you read. It stays open or closed the way you last left it. On a phone it opens over the document.

A wiki page lists its headings in the page tree instead. See [Wikis](wikis.md).

## See a page as Markdown

The Markdown button along the bottom of the editor (hover it and it says **Convert From Markdown**) turns the whole page into its Markdown text. Press it again to turn the text back into a page. To bring in Markdown from somewhere else, turn the page into Markdown, paste it in, and press the button again.

??? techspec "How the editor writes things in Markdown"
    Everything round-trips: callouts are written as Obsidian and GitHub write them (`> [!warning]`, `> [!warning]-` when folded), merged table cells as MultiMarkdown does (`||` and `^^`), columns as Pandoc fenced divs (`:::: {.columns}`), a drawing as its scene in an `excalidraw` code block, a `#` link as `[[task:12|Roll call]]`, a smart chip as `[[task:12:status|Roll call]]`, an embed as `![[task:12|Roll call]]` and a mention as `@[](4)`. An export to Markdown keeps each drawing's scene; Word and PDF exports leave drawings out.

## More tools along the bottom of the editor

A text document or wiki page has these along the bottom:

- **Speech To Text** (the microphone, where your browser can do it) types what you say.
- **Import Content** (the upload arrow) loads a document you exported as **Importable file (.json)** back into the page.
- **Read-Only Mode** (the lock) stops you typing by accident while you read. Select it again to unlock.
- **Clear Editor** (the bin) empties the page, after asking.
- The count shows how many characters and words there are.

A post has only the count, which shows how many of its 10,000 characters are left.

## Get help writing from AI

Where your community has AI switched on, select some text for **Writing help** (**Rewrite**, **Shorten**, **Fix spelling and grammar**, **Translate…**), or type `/` and pick **Continue writing**. A text document also gets **Summary** above it. Nothing goes in until you choose **Insert** or **Replace**. See [AI features](../account/ai-features.md).

## Mention people and link to things

Type `@` for a person, `#` for anything in the initiative, and `[[` to link to a tool or make one on the spot. See [Mentions & links](mentions-and-links.md).
