# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Edit a project's views where you see them.** Under a project's settings › Views, **Edit views** opens the project's views full screen, drawn with its own tasks. Pick a view at the top, then change what a board's card shows or which columns a table has and in what order, from the outline on the left or by clicking the part on the preview. Drag parts to reorder them, hide them, or add fields, properties, groups and plug-in parts from **Add**. A view's name, layout, default and a table's sort are on the view itself. Preview it at desktop, tablet and phone widths, undo and redo as you go, and nothing changes for anyone until you save. Editing views needs a tablet-sized screen or larger.
- **Lay out a project's task page.** **Edit task page**, beside **Edit views**, opens the same editor on the page every task in the project opens to, drawn with one of its tasks. Move parts between the header, the main column and the side, and into and out of sections; give a section a title and have it start folded; add the status, dates, comments, relations, plug-in parts and more from **Add**. A field taken off the page isn't lost: it's still shown, and can still be changed, under **More fields**. **Use the shipped page** puts the original back. The page and the views save together. On a board's card, parts now move between groups too.
- **Add, duplicate and delete views in the editor, and set what each one shows.** The editor's top bar adds a view, and its menu duplicates or deletes the open one; a deleted default passes to the first view left. A view's settings now hold the filters it's fixed to (assignees, due date, statuses, tags, archived tasks and properties), with the same controls as the task list. Everyone sees those tasks, and can narrow them further with their own filters.
- **Change a view or the task page right on the preview.** Pointing at a part on the preview names it and shows **+** points before and after it, which add a field or part right there; a table's columns have them too. The selected part has a handle to drag it somewhere else on the preview: beside another part, or into a group.
- **Plug-ins can keep their own data on items.** An installed plug-in can store small values on tasks, events, queue items, counters, gallery images and posts, and on its own installation, and find an item by one of them, so it needs no database of its own for that. A plug-in reaches only its own values, and only on items it can read.
- **Plug-ins on tasks.** A plug-in can declare fields, sections and actions for tasks. Members see a plug-in's values and run its actions in the initiatives where it is placed, with the roles it is placed for. Its fields can be shown as columns in a project's table, and an action the plug-in offers in a task's menu is there for anyone who can open the task. A board's card shows a plug-in's fields and sections only where a project's view places them.
- **Subscribe to a calendar from Google Calendar, Apple Calendar or Outlook.** Choose **Subscribe** on an initiative's calendars or the community's, and get a link for each calendar you want. Each keeps that app up to date and stays a separate calendar there. The link shows the calendar as you see it, and only while you can see it. It stops working if you leave the community, if your API access there is turned off, or if the calendar's initiative keeps its content in. It shows under Settings › Security with your API keys, where you can remove it.
- **Attach pictures and documents to a ticket or a report.** Asking for help, answering on a ticket and reporting something each take a few files, encrypted where they are kept. The places a picture was taken are removed before it is stored. The people handling a ticket or a report see pictures blurred until they choose to look, and files are deleted once the ticket has been closed long enough.
- **Hide reported content while the platform looks at it.** Sending a report to the platform now asks whether to leave the reported thing up or hide it. Hide it when the police or a court asked for it to be kept, or it may be illegal: it disappears for everyone in the community, admins and the moderator included, and nobody there can change or delete it until the platform puts it back, moves it to the trash, or deletes it for good. A report of something illegal is hidden by default. A comment's replies stay visible under an "Unavailable" placeholder, and a community with hidden content isn't deleted for good until the platform has dealt with it.
- **Moderation access.** Platform moderators can request a new access level, Moderate, which reads everything in a community, including what is held, and changes nothing. Releasing a hold needs it, and it is never self-issued.
- **Moderators act on what they're shown.** A shield menu on comments, posts, pictures, wiki pages, queue items and events lets a community's moderators remove it with a reason, lock its comments, clear its reactions or hold it for the platform. A removed comment leaves a line saying why where it was, and its replies stay. Whoever wrote it is told why, never by whom. Settling a report as removed or warned now does it, and a warning sends the member the moderator's own words.
- **A moderation log.** The moderation page's new **Log** tab lists what moderators have done, with the words a removed comment said, and puts back a removal.
- **Reporting something illegal tells the platform too.** A report names the law it falls under, and goes to the community's moderators and to whoever runs the server at once; the reporter follows it under their tickets. Where the server takes no reports, the reporter is told who to contact. A child-safety report takes no attachments.
- **Report wiki pages, queue items and events.**
- **Limit a plug-in to the operations community.** A server owner can mark a plug-in **Only the operations community**, in its settings or in `PLUGIN_SERVICES_CONFIG` (`operations_only`). Only that community can find, install or use it, and a copy added anywhere else stops working until the switch is off. Nothing is deleted.

- **The server raises its own security cases.** A run of something that looks wrong opens one case in the security project: many failed sign-ins from one address, a spent session token used again, many wrong second-factor codes, a one-time token presented twice, a new operator or owner, an operator breaking glass, a cleared second factor, an exported user list, an API key reaching past what it may do, and floods of refused cross-site requests, rate-limit hits or captchas from one address. Counting costs no database writes per attempt, and a run that goes on stays one case.
- **Report a security problem from the app.** Under User settings › Security, in My Tickets and in the command palette. You follow it, and talk with the team about it, in My Tickets.
- **`/.well-known/security.txt`** names the server's security address and, where reports are taken in the app, the form.
- **"This wasn't me" tells the people who run the server.** Following it from an account email now opens a security case about the account, or names who to tell where nobody is set up to hear it.
- **More of what was refused is in the audit log:** replayed billing tokens and plug-in assertions, API keys reaching past their scope, and secret-key rotations.
- **Ask for help about your own account from anywhere.** Asking for help now starts with what it is about: your account, billing or something else, wherever the server takes help requests, and the community you are in where it takes them from there. Whoever holds a community's seat can also ask for a copy of its data, or for it to be deleted.
- **"Ask for help" where notices said to contact whoever runs the server:** beside the age question, a read-only or suspended community, and a community that is out of seats or can't be listed for want of them. Where the server takes no help requests, it shows the address it gave.
- **Appeal a suspension.** A suspended account can appeal from the screen it signs in to, follow the appeal there and talk with the moderators about it, one appeal at a time.
- **Send feedback.** From the account menu or the command palette: an idea, a problem, praise or something else, with screenshots and, unless you remove it, where the app was — its version, platform, language, theme, page and window size, never anything that names you or what you opened. A problem that needs an answer goes to support instead, and you're told when your feedback has been read.
- **Support and moderators see the communities list.** Operator dashboard › Communities lists every community, deleted and suspended ones included, for support and above. Each row offers only what your role allows: its billing in the support console, asking for access, and for operators and owners its status, the operator console, Manage and breaking glass.
- **Moderators suspend communities.** Under a Moderate grant on it, a moderator suspends a community or lifts the suspension from its row. A deleted community can be suspended too, which stops its deletion countdown; lifting that puts it back into deletion with the whole window ahead of it.
- **More account actions for staff:** sign an account out everywhere; clear the names it goes by in its communities, its status line or its decorations; and see the open cases it filed or is the subject of, with links.
- **Pick a community by name** when asking for access or breaking glass, rather than typing its number.

### Changed

- **A view decides what a board's card and a table show, for everyone.** The board's **Fields** menu and the project table's **Columns** menu are gone, along with the choices they kept on each device. A project's views are laid out once, in **Edit views**, by whoever can configure the project. A table shows title, dates, priority, tags and comments until its view adds property or plug-in columns.
- **Access grants name people by handle.** The Access tab and its API name whoever asked for or approved a grant by their handle, not a masked email address. API: `AccessGrantRead.user_email` and `approved_by_email` are replaced by `user` and `approved_by`.
- **Staff change their own account from their own settings.** The operator dashboard no longer acts on the viewer's own account; it offered little there already.
- **A project's saved filters are now views.** One menu on a project lists its views, and each is a layout with its own filters: Table, Board, Calendar, Incomplete, Unassigned and Mine to begin with. Saved filter sets someone made or changed became views of their own with the project's default layout, and links to them still open them. Your own filter changes on a view are kept for you alone, and Reset to view puts back its filters. People who can configure the project can save the current filters as a new view, update a view, and rename, reorder, delete or choose the default one under the project's settings › Views.
- **A task's page saves each field on its own.** There is no Save button any more. A status, a priority, a person, a tag or a date saves as soon as you pick it, with Undo for a move or a cleared value. A title saves on Enter or when you click away, and Esc puts it back. The description opens on its preview with its own Save, keeps your draft on the device until you save or discard it, and if someone changed it while you were editing, it shows you their version before anything is overwritten. Start and due dates are one control, and a change to a repeating task still asks whether it applies to this one or all that follow. Each field shows its own saving state, and one that fails keeps a Try again.
- **Layouts fit foldable phones and tablets.** On an unfolded foldable or a tablet held upright, forms go two fields to a row and cards fill as many columns as fit, rather than waiting for a laptop-sized screen. On a large screen, cards stop at the columns they had before and grow wider instead. The sidebar now stays open beside the page from the width of a tablet held sideways, where before it waited for 1024 pixels.
- **Plug-ins are built with SDK 6.0.** Initiative serves plug-in API 6.0. A plug-in's own screens are declared as `pages` rather than `embeds`, and a plug-in can declare fields, parts and actions for tasks and other items. A project no longer has a `default_view_mode`: its views decide which one it opens on. Installing or updating a plug-in here needs a release built with SDK 6.0. Plug-ins already installed keep working.
- **Dates and numbers format faster** on every screen that shows them. Building a formatter was most of what a large board spent redrawing.
- **Backups keep each initiative's join policy.** An initiative restored from a backup takes requests or lets members join as it did where it was exported. Backups made before this restore as private, as they did.
- **Large boards draw faster.** A 300-card board appears about a fifth sooner, and switching a field on or off in its Fields menu redraws it about five times faster.
- **Escalate is now Send to the platform** on a report card, and a settled report says "Sent to the platform".
- **Only moderators take down other people's comments.** Delete is for your own comments; project managers no longer delete anyone else's. Community admins and roles with Full access remove them instead, with a reason. Community admins see a notice about it after upgrading.
- **Deleting your comment leaves its replies.** It goes to your trash as before, and the replies under it stay, under a line saying you deleted it.
- **A report of something illegal, or of "Other", says what is wrong.**
- **API: `DELETE /comments/{id}` is the author's alone**, and the comment list says whether the thread is locked and whether the reader moderates it.
- **API: filing a ticket and answering one take `multipart/form-data`.** `POST /api/v1/me/tickets` takes the ticket as JSON in a `payload` field, and `POST /api/v1/me/tickets/{task_id}/replies` takes the answer in a `body` field, each beside any `files`.
- **Signing out of the phone or desktop app keeps your encrypted messages.** Sign back in with the same account and they are all there, with nothing to sync, along with anything sent while you were away. Signing in to another account on the same app keeps each account's messages apart instead of deleting the first one's. A browser still clears its messages when you sign out.

### Fixed

- **Your recently opened items, favorite projects and project order are yours alone.** Nobody else in the community can read or change them, admins included.
- **Only you can answer a poll or mark a notice read as yourself.** Admins can't change your answer either. Others still see the counts and who answered, as before.
- **Only a comment's author can change or delete it, and only you can add or take off your reactions.** Comments, posts and reactions always carry the person who wrote them as their author. Moderators still take comments down and clear reactions, and an import still keeps the authors it maps.
- **Join requests are seen only by whoever asked and the people who answer them.** Other members of the community no longer see who asked to join an initiative.
- **A gallery without a cover shows its newest pictures again.**
- **The project task table keeps its rows current.** A task's checklist progress, a swapped assignee and its blocker count now update in the table as they change, as they already did on the board.
- **The task tables' Columns menu names its columns** ("Start date", "Comments") instead of showing their internal names.
- **A "New device signed in" prompt about a device that is gone can be cleared.** When the device it named had signed out or been removed, Verify and Not mine both failed with "That device is not set up for encrypted messages" and the prompt stayed. It now goes away on its own, and either button closes it.
- **Encrypted messages set themselves up after a reload during setup.** Reloading or opening a second tab while a browser was first setting up messages could leave it showing "Encrypted messages could not be set up on this device" until reloaded again. It now picks up where the other tab left off, and the message has a Try again button.
- **One notification when a new device asks for your message history.** Each of your other devices was notified once for every device the new one asked, so an account with four devices got four at once.
- **New devices are named in words.** The "New device signed in" prompt says "Chrome on Windows" rather than the browser's full user-agent string.
- **The phone and desktop apps each show as one device.** Every new sign-in from the app added another entry under Settings › Security, and could leave its messages behind. Signing in again now continues the same device. Entries left by earlier sign-ins stay until you remove them or they expire. The list now shows your devices first, then your browsers.
- **A browser whose sign-in ran out leaves the list.** It no longer stays under Settings › Security as "not signed in".

## [0.75.3] - 2026-10-08

### Added

- **Task tables sort by status and by tag.** Status sorts in the order of the project's board, and tags by each task's first tag alphabetically, with untagged tasks last.

### Fixed

- **Direct messages arrive again.** The first message to a new device never opened on the other end, so messages stopped arriving and a new device never got its history. Messages left waiting open once the receiving device is updated. Your own devices may ask to be verified once more, and conversations may say a key changed.
- **A new device gets its whole history**, however long, and even while your newest conversation is an invitation you haven't answered. The notice asking you to verify it goes away once you have.
- **A device keeps receiving messages** when some sent to it can never be opened, such as ones from a device that has since signed out. Those are cleared instead of holding up everything behind them.
- **The notification list scrolls again.** With more unread than fit, everything past the first few was cut off with no way to reach it.
- **The prompt to turn on push notifications sits below the notch on iPhone** instead of under it, where its text was hidden.
- **Updating the desktop app no longer leaves a white window.** The splash screen covers the window while it reloads into an update, in your theme. An update that takes a while to start on a slow disk is no longer undone and offered again. One that really doesn't start is undone and its download removed, rather than kept on disk.
- **The name you go by in a community is used everywhere in it.** Notifications and their emails, post bylines, who read a post or voted in a poll, who uploaded a picture, the moderation roster, and your cursor in a shared file all used your handle. Exports now say who exported them by that name too, and a project report lists its assignees by name. Notifications you already have keep the handle they were sent with.
- **Exporting a project's tasks keeps your view of it.** From the table, the export lists tasks in the order you sorted them, as it already kept your filters, and a selection exports in that order too. Exporting a project from its settings now starts from the same filters and order, which you can still change before exporting.

## [0.75.2] - 2026-10-07

### Changed

- **A community's location is one field you type into.** A country, a city or a full address, as short or as long as you like, with places suggested as you type and the closest ones first. Pick one to put the community on the map; the card shows the location exactly as you wrote it, with your own name for the place in front. **Near me** sorts by distance, so a community just over a border counts as nearby.
- **A file's featured image keeps its own shape.** It used to be cropped to a wide banner across the top of the file; now it shows whole, at its own proportions, and stops short of filling the screen.

### Fixed

- **"Every current initiative" places a plug-in in every initiative in the community**, including ones you are not a member of. It used to reach only your own initiatives, so automations stayed silent everywhere else while the setting said every initiative. If you chose it before, open the plug-in's settings and choose **Every current initiative** again to reach the rest.

## [0.75.1] - 2026-10-07

### Changed

- **Sign-up refuses anyone under the minimum age for an account where they are**, from 13 to 16 depending on the country, and no account is made. This only applies while the age check is on. **Server operators:** set `CLIENT_COUNTRY_HEADER` so the minimum follows the country; unset, 16 applies to everyone.

### Fixed

- **Turning the age check off now stops every age question.** With **Check members' age** off under **Platform settings › Community**, every account counts as an adult: nobody is asked for a date of birth, plug-ins with a minimum age open for everyone, and direct messages work without answering.

## [0.75.0] - 2026-10-07

### Added

- **A Projects marketplace.** Start a project from a ready-made one: a sales pipeline, a hiring pipeline, a bug tracker, a content calendar, a grant tracker, a product launch or facility maintenance. Find them on the marketplace's **Projects** shelf, or under **From the marketplace** when you create a project. Start blank or from a filled-in example, and its dates land on the day you pick.
- **Passkeys work inside the Android app**: signing in, adding one, and answering a community that asks for one, without leaving for the browser. Where the phone won't let the app do it for your server, and on iPhone, the browser opens as before. **Server operators:** nothing to set up, but if your reverse proxy answers `/.well-known/` itself, pass `/.well-known/assetlinks.json` through to Initiative.
- **Plug-ins can have a minimum age**, which may differ by country. Someone younger than a plug-in's minimum where they are can't open or use it; their community can still install it. **Server operators:** set `CLIENT_COUNTRY_HEADER` (`CF-IPCountry` behind Cloudflare) so the limits apply by country; unset, a plug-in's highest minimum applies to everyone.
- **Billing insights** for operators and owners, under **Operator dashboard → Billing** on servers connected to a billing service: revenue, subscribers and cancellations across every community, without opening any one of them. The new `billing.insights` capability gates it.
- **"This wasn't me" in account emails.** Signs your account out everywhere and turns off its API keys. When a change looks out of place, the email to your other addresses can undo it too.
- **Some sign-in changes wait two days** when made from somewhere your account is new to, with **Cancel the change** in every email and in your settings. Signing in with a passkey skips the wait.
- **Remove a phone or computer** from **User settings › Security › Where you're signed in**. It is signed out and loses the messages only it held.
- **A desktop app** for Windows, Mac and Linux, with system notifications, an unread count and a tray icon. Get it from the **Download** page. **Server operators:** nothing to set up; the **Phone and desktop notifications** switches (formerly **Mobile notifications**) cover it.
- **Duplicate more.** Counters, queue items, events and wiki pages can be duplicated on their own, and any tool but a notice can be copied into another initiative from **Settings › Advanced**. A duplicated task keeps its links.
- **A display name for each community**, set from its **Members** page.
- **Keep an initiative's content in**: a switch under **Initiative settings › Export** that stops exporting, sharing or moving content out of it.
- **Moderators can revoke someone's API keys** from **Operator dashboard › Users**.
- **Prometheus metrics** for pages opened, tools created and active accounts, and **opt-in browser analytics** through Grafana Faro (`FARO_COLLECTOR_URL`). See **Running a server › Configuration**.
- **Follow the help requests you've filed** from **My Tickets** in the sidebar: where each stands, what the team said, and your answers, updated as they come. The team replies from a panel on the case, kept apart from its comments. **Server operators:** on the **Intake** page, pick the statuses that wait on the requester and that their answer moves a case to (**Set this up for me** creates both); security and moderation each need an initiative of their own.
- **Run a dashboard as Individual or Initiative.** Under a dashboard's **Settings → Details**: Individual (the default) shows each person only what they can see; Initiative shows everyone the same numbers, with full read access to the initiative. A new role permission, **Run dashboards as Initiative**, says who may turn it on or change such a dashboard's tiles; managers always can.
- **Filters can match all or any.** Choose once at the top, add a group for the other kind, and choose to leave out, include, or count only archived work and templates. Deleted things are never counted.
- **Push notifications without Firebase.** Turn on **Send push notifications** and leave the rest empty: your server registers itself once with BeyondersStudio's push relay and sends through it. iPhone pushes always go through the relay; with your own Firebase service account, Android pushes still go straight to Firebase. The relay passes the text on and never keeps it. Your server never holds a phone's token for the relay: the app registers it with the relay itself and gives your server a handle that reaches that phone for your server only. Your server contacts the relay only once a phone that needs it shows up (an iPhone, or Android without your own Firebase), and tells it nothing about where it runs. See **Running a server › Push notifications**.
- **A timeline can be drawn in years.**
- **Close an event's RSVP.** Under an event's **Settings → Attendees**, turn off **Anyone who can see it may RSVP** and only the attendees you add can answer. On, as before, answering adds you to the attendees. A repeating event's occurrences follow the series.
- **Plug-ins can show your community's usage** on **Community settings › Usage**, below storage and members.
- **A plug-in's listing shows its minimum age** where it declares one, for the country your browser is set to.
- **Report a marketplace listing or a plug-in** with the flag on its listing page or at the top of the plug-in. Reports go to whoever runs the server. Plug-ins BeyondersStudio publishes have no flag.
- **Plug-ins can create custom properties.** A community can grant a plug-in **Properties**, which lets it read an initiative's property definitions and add new ones. A plug-in that can change something, such as a task, can still fill in that thing's properties without it.
- **A plug-in can say which plug-in API it needs**, as `min_plugin_api` in its listing or manifest (`"4.1"`). A server that doesn't provide that API refuses to install or upgrade to it, and says why; listings that don't say keep working. The plug-in API document (`/api/v1/plugin-platform/openapi.json`) is now versioned as the plug-in SDK it matches, not as the server release.

### Changed

- **The paw print trophy is redrawn** as the project's own artwork, and **the raised fist trophy now uses a public-domain drawing** of the same symbol, so no trophy carries a share-alike licence any more.
- **A phone's sign-in keeps one push registration**: a new token replaces the one it held, and an account can register at most 30 an hour. One account can no longer pile up tokens the push relay answers as dead, which would get the whole server's pushes suspended.
- **Anything under `/.well-known/` that Initiative doesn't serve answers 404**, not the app's page, and the app association files are cached for an hour.
- **The old `morelitea` publisher is no longer trusted.** Plug-ins this project ships are published as `beyonders-studio`, and the seeded `morelitea` publisher is removed on upgrade, or, if anything is still registered or listed under it, kept as an ordinary unverified publisher.
- **Files have a new icon**, a stack of pages rather than a scroll, since a file can be a spreadsheet, a whiteboard, an upload or a link as well as a document.
- **A task's assignee chip names two people** before counting the rest, so a task held by two shows both names.
- **A new wiki page opens ready to write in**, rather than as a blank page to read.
- **Your date of birth is kept, encrypted**, and every account is asked it once. It's used only to check age limits, never shown back, and never sold. If it was entered wrongly, whoever runs the server can reset the question.
- **Documents are now called Files.** Text documents, whiteboards, spreadsheets, links and uploads live in the Files tool. Upgrading moves what is already stored, including plug-in grants, webhook subscriptions and the SQL in dashboards. Links to the old `/documents/…` pages and `/go/document/…` no longer open, and saved list layouts for the tool start fresh. Backups made before the rename still restore.
- **Plug-ins that can write to a queue or counter group can add its items and counters**, edit counters, reset all counters and sort them.
- **The documents table drops its Projects column**; a document's links show on its own page, as every tool's do.
- **A project list works like every other tool's**: grid, list and tag layouts, the shared filters and table sorting. Drag projects into your own order on the first page; pin and favourite from each card. The pinned section and the favourites-only filter are gone, and favourites stay in the sidebar.
- **Apps are now called plug-ins.** **Server operators:** rename `APP_PLATFORM_SIGNING_KEY_ID`, `APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM` and `APP_SERVICES_CONFIG` to `PLUGIN_PLATFORM_SIGNING_KEY_ID`, `PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM` and `PLUGIN_SERVICES_CONFIG`.
- **Dashboard queries read a file's type, size and name through `current_version`** (`current_version.file_size` on `documents` and `gallery_images`), the version the file shows. The new `document_versions` and `gallery_image_versions` datasets hold every version.
- **Every tool's list can tag, duplicate and delete several items at once**, as documents could. The documents list now works like the other tools' lists, and the view you pick (archived, templates) is kept in the address.
- **Plans can be changed from the phone apps where the store allows it.** The iPhone app on the US App Store, and the Android app from Google Play in the US, UK, Australia and the EEA, open the billing portal in your browser. Elsewhere the apps still show your plan without offering to change it, and apps embedded in a community are told so too. An Android app installed outside Google Play works like the web.
- **The Android app is now `studio.beyonders.initiative`**, published by Beyonders Studio. It installs beside the old app rather than updating it, and upgraded servers no longer accept the old app: install the new one, sign in, then uninstall the old one. **Self-hosted Firebase:** register an Android app under the new package name; see **Push notifications**.
- **The image is now `ghcr.io/beyonders-studio/initiative`**, on the GitHub Container Registry, and the project lives at `github.com/beyonders-studio/initiative`. Docker Hub's `morelitea/initiative` keeps the releases it has but gets no new ones: change your compose file's `image:` line to `ghcr.io/beyonders-studio/initiative:latest` (or `:stable`, or a version). The update notice now reads the project's GitHub releases.
- **First-party plug-ins are published as `beyonders-studio`** (`beyonders-studio.github`, `beyonders-studio.automations`, …), and the default marketplace registry moves to `https://beyonders-studio.github.io/initiative-developer/public/`. **Self-hosted:** a plug-in installed under a `morelitea.` id is no longer treated as first-party; remove it and install its `beyonders-studio.` listing. If you set `MARKETPLACE_REGISTRY_URL` to the old address, change or unset it.
- **The pricing page shows the billing portal's own plan cards**, in your language and your currency, laid out the same as on the portal.
- **The `route` label of `initiative_page_views_total` now reads `/c/$communityId/…`.**
- **Accounts no longer have a name.** You're your handle, or the display name you set in a community. Saved names are deleted on upgrade. **Server operators:** `FIRST_OWNER_FULL_NAME` is ignored.
- **Mentions always show the name a person goes by now**, or **Former member** once they've left, and search finds mentions by that name. **Server operators:** the first start rebuilds each community's search index.
- **The server prepares documents for live editing**, and live editing works across several copies of the server. **Server operators:** the editor helper uses about 90 MB while running; see **Running more than one copy**.
- **Changing your email addresses asks you to confirm it's you.**
- **The jackalope mascot is called Yonder now**, not Chester.
- **The phone and desktop apps open straight to sign-in.** The website's front pages (welcome, pricing, download, what's new) are no longer part of the apps.
- **On iPhone, an app update is sent to the App Store**, not to an APK download.
- **The iPhone app shows the curated marketplace**: listings that ship with Initiative and those from the Initiative registry. Plug-ins a community already added open too; one BeyondersStudio doesn't publish shows a one-time note first saying who made it.
- **The Android app connects to `https://` servers only.** **Server operators:** a server on plain `http://` needs HTTPS before the app can reach it; browsers are unaffected.
- **The phone app never goes back to an update older than itself**, and on iPhone a new feature release arrives through the App Store.
- **An app installed from Google Play is sent back to Play** when it needs updating.
- **The phone and desktop apps stay signed in for ninety days** of not being used, and show as one row each in your sessions. An app last opened before 0.70 asks you to sign in once.
- **The sign-in page says which server you're signing in to.** In the phone app, tap its name to switch servers.
- **API access is set per member.** A community's superadmin turns one person's personal API keys on or off from the **API access** column in **Community settings › Users**, which stops keys they already made too. It replaces the community-wide switch on the **Security** tab and, like it, applies only where the server grants the community the security standard. Members of a community that had keys switched off start with them off. Personal API keys never reach a community through an access grant.
- **Rate limits count per account, not per network**, so people sharing an office address no longer share a limit or lock each other out.
- **Links in notification emails sent before this release no longer open.** Open the notification in the app instead.
- **User settings are reorganised.** **Interface** is now **Preferences**, and the **Danger Zone** tab has moved into **Account**.
- **One header for every tool page**, with status, tags and properties editable in place, and a tidier, more consistent layout throughout.
- **Every tool list can be shown as cards, a list or by tag**, and dashboard, counter and queue cards preview what's inside.
- **Connections look the same on every tool and wiki page**, as cards or a list.
- **A document leads with its featured image**, replacing the **Metadata** section.
- **An initiative's page is quieter**, with who's online shown as faces.
- **Expanding the guild rail shows each guild as a card.**
- **Calendars:** pick which to see from the title, show or hide project tasks from **Filters**, and export from **More actions**.
- **No initiative is the default any more.** A "Default Initiative" can be renamed, archived or deleted.
- **The app asks where your Initiative runs** on its first screen, and signed-out pages show which server you're on.
- **The app opens faster.**
- **Documentation and Ask for help are separate buttons** at the foot of the sidebar.
- **Clearer query builder.** Plain names for columns and fields ("Due date", not `due_date`) and shorter, plainer wording throughout.
- **"Published figures" are removed.** **Run dashboard as → Initiative** replaces them. A dashboard that published figures goes back to showing each person their own numbers on upgrade; switch it to Initiative to share them again.

### Fixed

- **Signing out of the phone app, or pointing it at another server, stops its push notifications** from the server it left, also when push was set up before the app last restarted.
- **A listing no catalog directory publishes any more is withdrawn**, even when no directory is set. This removes the old built-in Automations listing earlier releases left in the marketplace. A community that installed it keeps what it has.
- **Delete Node in a document's right-click menu removes a smart chip or mention** when opened on one, instead of doing nothing.
- **Notifications inbox.** Clicking a finished export now downloads it, as the bell does, and items are grouped under the day they happened where you are.
- **Notification switches reach queued email.** Turning email off for a community or the server, or hiding notification content, now also applies to emails already waiting to go out, such as a digest held for its next send.
- **An imported dashboard keeps its tags**, as other tools do.
- **Queues, counters and calendars** keep their own tags in backups. A queue item's notes can be cleared, a queue, counter group or counter can no longer be saved with a blank name, and a trashed queue item no longer shows when a deleted queue is opened.
- **Galleries and wiki pages you've opened are kept for offline use**, as other tools' are. The command palette shows a link document's site icon, and the image dialog in the editor is translated.
- **A plug-in can create things again.** The owner record a plug-in's new item gets was still written under the plug-in's old name, so creating anything failed.
- **Someone who loses access to a calendar, queue or other tool is taken off what is in it.** Event attendees, people on queue items and person fields now let go of them when sharing changes, as task assignees already did.
- **Files restored from a backup or brought in with a wiki or gallery import keep a version history and a type**, as uploaded ones do; a file whose type isn't one the tool shows is skipped and reported.
- **A comment that fails to post, save or delete says so in words** rather than showing a raw message key.
- **Importing a link document checks its address**, as creating one does: an address that isn't `http://` or `https://` is refused.
- **On a phone browser, the sidebar's bottom row is no longer hidden behind the browser's toolbar.**
- **Image captions in documents and wiki pages are saved.**
- **`RATE_LIMIT_STORAGE_URI` accepts a `redis://` URL.**
- **The phone and desktop apps keep your messages when a session times out**, and message notifications reach current phones again.
- **The twelve-hour session standard no longer signs people out every fifteen minutes** while they're working.
- **Password managers no longer lock accounts** by submitting the sign-in form several times.
- **Unlocking an account or resetting its password lets its holder straight back in.**
- **Built-in dashboard templates update again** after upgrading to 0.74.
- **Dialogs taller than the screen scroll**, so their buttons stay within reach.
- **Repeating events keep their dates within the calendar**, and a range with too many occurrences asks for a shorter one.
- **A post published after its poll's deadline** opens the poll instead of posting it closed.
- **Voting in a poll or editing a notice no longer marks it unread** or raises its "Read by" count.
- **Dashboard settings accept only the values a widget asks for**, including in imported dashboards.
- **A new dashboard offers Run as Initiative straight away** to people who may turn it on.
- **A failed dashboard update shows one message, not two**, and a poll nobody has answered says so.
- **Comments offer Delete only to people who can delete them**, and ask first.
- **Reports and help requests:** escalated reports carry what reporters wrote, repeat reports add to the case, the help form hides while the support project is archived, non-owner operators can switch help requests on, and both are limited per account.
- **Access grants show as expired** when their time runs out.
- **The operator's Users page no longer offers actions on accounts above your role.**
- **A community reached through a settings grant shows its icon and banner.**
- **A document filed in a wiki shows its own connections.**
- **New queue items and events attach only things from their own initiative.**
- **Project filter presets show in your language**, and the time zone picker shows UTC.
- **An account made through a provider with no email address can make a confirmed address its primary.**
- **Grouping by week, month, quarter or year works in charts.** Dates showed as long raw numbers and came back out of order; they're now labelled by their period and sorted oldest first.
- **Heatmaps show weekly, monthly, quarterly and yearly data** instead of scattering it over a day calendar.
- **A wiki's "Show when a page was last updated" setting is saved**, and editing a wiki or one of its pages dates it.
- **A new, copied or moved wiki page shows its tags and properties straight away.**
- **Exporting a wiki keeps its settings**: page order, contents depth, connections, last-updated, reading width, accent colour and template page come back when it is imported.
- **Plug-ins with a wiki's or gallery's write access can add, edit and move its pages and pictures**, and upload new versions of a picture. Removing them stays with people.
- **Community locations.** A community can say where it is, from just a country down to a street address, with its own name for the place ("Queen Anne Neighborhood, Seattle, WA"). It shows on the community's front page and its card; street and postcode stay behind a hover or tap. The directory's search finds communities by place too, country names included, and **Near me** puts the closest ones first. Sign-up asks where you are when you're looking for a community.
- **Clearing an event's description or location saves.** The emptied field used to come back.
- **Saving an event or calendar with an empty required field is refused** instead of failing with a server error.
- **A calendar's color follows what was saved**, and can no longer look cleared.
- **A calendar or event link you can't open says so** instead of loading forever.
- **iCal import problems show in your language.**
- **An initiative's calendar shows only its own tasks**, and the community calendar shows none.

## [0.74.0] - 2026-10-01

### Added

- **A friendlier sign-up** that asks what you're here for: joining by invite, joining a public community, a space for your own to-dos, or a community for a group. A personal space starts with a **To do** list, and a group's community starts with its first initiative and an invite link to send.
- **A People tab** showing who's in your community and who's online.
- **Repeating events and tasks**: change just one occurrence, skip one, or change the rest of the series. New repeats such as "the last Friday" or "the first work day of the month", and every date shows on the calendar.
- **Custom properties on every tool**, with filters on every list.
- **Filtered exports**, using the same filters as each list.
- **What's new** shows release notes right in the app.
- **A `stable` image tag** for servers that would rather wait. A release moves to it once it has been out three days with no reported regressions; `latest` still gets every release right away.

### Changed

- **A new front page and Download page.**
- **Chester is now a jackalope**, from the Beyonders Studio logo.
- **Search and filters cover the whole list**, not just what's loaded.
- **All-day events are the same days for everyone**, whatever their timezone.
- **Comments open on the newest conversations**, with **Load older comments** for the rest.
- **If your server doesn't use passwords, nothing asks for one.** Deleting your account, setting up two-factor or changing passkeys asks for a recent sign-in instead, or emails you a code.
- **Initiatives have their own icon**: the figure from the Initiative logo, in place of the members icon.
- **App and API integrations may need updating.** Repeats are now standard `RRULE` text, counters are changed through `/counters/{id}`, and many routes were merged into others.

### Removed

- **The KMS key setting for file storage.** Use the bucket's own encryption instead.

### Fixed

- **Live documents stop flashing "Syncing…"** while you type, and wiki page saves and offline edits are no longer overwritten.
- **Calendars with repeating events export again**, and imported events keep their days.
- **Repeats carry over** from Todoist, TickTick, Vikunja and project templates.
- **Property filters are fast** on big lists.
- **Trash and archive work for archived things.** They can be deleted, restored and handed to a new owner, and nothing is restored inside something that's still in the trash.
- **The document toolbar shows which formatting is on.**
- **Sign-in:** you can't turn off your own only way to sign in, and wrong passwords in settings count toward the account lock.
- **Changing your password stops notifications to every phone** until it signs in again.
- **Only a community admin can remove a moderator.**

## [0.73.2] - 2026-09-29

### Fixed

- **A trusted sign-in provider's passkey sign-in counts as a second factor**, for providers such as Pocket ID that report a phishing-resistant sign-in rather than naming a second factor. New Pocket ID connections trust it by default.
- **Spreadsheets accept a decimal without its leading zero.** Typing `.7` into a cell now stores the number 0.7 rather than text, and a formula such as `=.7*2` works instead of showing an error.

## [0.73.1] - 2026-09-29

### Added

- **Ignore someone by handle** from Settings › Privacy › Ignored accounts, the same way you connect. API: `POST /me/ignored`.

### Changed

- **Trash shows 25 items a page**, with page controls past that.
- **A new device is verified with four pictures**, different every time, shown side by side on the new device and one you already use. The device code in Security settings and safety numbers are gone; when somebody you message changes their devices, the conversation says so in one line.

### Fixed

- **Upgrading to 0.73 no longer stops at startup** on a server set up with a single database URL.
- **Breaking glass only asks for a code if you have two-factor set up**, or the server requires it for your role. A second factor from single sign-on counts, and another operator setting it up no longer asks it of you.

## [0.73.0] - 2026-09-28

### Added

- **Safety numbers in messages**, so you can check who you're talking to. A new device has to be approved by your other devices.
- **Embeds** (`![[`) and **task checkbox chips** in documents. An embedded document or wiki page shows what it says, not just its name.
- **Callouts and embeds fold** to their first line, and stay folded for everyone who opens the page.
- **Full-size pictures**: click a picture in any text to open it.
- **Unread dots that lead to the item**, with unread comments highlighted.
- **One-tap 👍** on comments and posts.
- **An email when your password changes.**
- **Export on the calendars page** saves the calendars on screen, every date, as one `.ics` file. Anyone who can see a calendar can export it. API: `GET /c/{guild_id}/exports/events`.
- **Resend verification email** in the platform Users menu, for an account that never confirmed its address. It sends the sign-up confirmation again, and an invite the account was waiting on still joins.

### Changed

- **Update the Android app from its APK**, since this release changes the app itself.
- **Reconnect your app accounts** once, such as GitHub.
- **Password sign-in pauses** after repeated wrong answers, for longer each time, up to four hours. Passkeys keep working, and resetting your password from the email ends the pause.
- **A phone restored from backup asks you to sign in again.**
- **Links to other sites open in a new tab.**
- **Comments show the newest conversation first.** Replies still read in order.
- **Pictures from other sites show as links.**
- **Ticked checklist lines stay readable** instead of being crossed out.
- **Only people who can open something** can be assigned to it, invited to it or notified about it.
- **Files belong to their initiative.** A picture or file in a page opens for anyone in that page's initiative. Pasting one from another initiative saves a copy, and moving a task to another initiative takes copies of its pictures.
- **Opening something marks its notifications read.**
- **Mentions in the same document** make one notification.
- **Read notifications clear after 30 days.**
- **Community calendars belong to admins.** Members add events to the ones shared with them.
- **Hidden calendars are remembered** in each community.
- **Ticking tasks in a table is instant.**
- **The trash shows a page at a time**, newest first.
- **If you never verified your email address**, verifying it now, with an emailed code or through your organization's sign-in, clears the account's password, passkeys and second factor. Your communities and content stay; set up new sign-in methods from Security. If your address is already verified, nothing changes. Servers without SMTP automatically verify all emails on sign up and are not impacted.
- **Improved efficiency and security.**

### Removed

- **API routes the app no longer uses**: single reads of an access grant, an app registration, an app's placements, your consents to an app and a target's reactions; editing a community's group rule; clearing one view preference; the smart-chip kinds list; each tool's `DELETE …/view` (use `/recents`); `POST /auth/verification/send`; and a community's `POST /users/{id}/approve`. The lists and detail reads carry the same data.

### Fixed

- **Platform account actions reach only accounts at or below your own role.** Reactivate is for deactivated accounts; lift a suspension or restore a deletion from their own actions.
- **Switching communities is quicker.**
- **API:** the member list (`GET /c/{guild_id}/users/`) and both trash lists return pages.
- **Dashboards load faster.**
- **Leaving an initiative** takes you off everything in it.
- **A picture shared by several pages** stays while any of them still shows it, including pages you can't open.
- **Signing out of the app stops its notifications**, and so does signing out other devices or resetting your password.
- **Whiteboards and offline edits** are no longer lost.
- **Large spreadsheets** keep up with your typing.
- **Duplicated file documents** include the file.
- **Notifications** open the event or page they're about.
- **The Markdown view** keeps smart chips, `#` links and @mentions instead of turning them into plain words, and a `|` inside a table cell no longer splits it.
- **Erased accounts** show as "Deleted user" everywhere they were mentioned.
- **Exports that keep failing** stop and tell you.
- **Jira and Confluence CSVs** arrive as spreadsheets.
- **Comments** go to the trash and come back with their item.
- **Queues and counters** reconnect after a dropped connection.
- **Tag pages** list every tool.
- **Archived projects** show their tasks again.
- **Signing up in the app with an emailed code** keeps you signed in.
- **Signing up with a password or passkey** on a server that sends email: confirming your address now lets you sign in, and an invite sent to that address joins you to its community when you confirm.

## [0.72.0] - 2026-09-24

### Added

- **Import from Jira and Confluence** — **Community settings → Data** reads a Jira or Confluence site directly with an API token, or a Confluence space from its HTML export. Projects, issues, sprints, comments, attachments and page trees come across, and the links between issues and pages still work after the move. The token is deleted once it has been read.
- **More in the editor** — callouts, status pills, merged table cells, drawings and Mermaid diagrams, all from the `/` menu.
- **Your sessions, in one place** — **My Settings → Security** lists every browser and phone signed in to your account. You can sign any one of them out, or all of them except the one you're on.
- **Control what notifications carry** — platform and community **Security** settings choose whether notifications may go to phones and email, and whether they may name what they're about. Where the two disagree, the stricter one wins.
- **Mentions in task descriptions** — type `@` to name a member of the initiative or `#` to link anything in it, the same way comments do. The people it names are notified once, when they are first added, and the things it links show under **Linked from**.
- **Pictures in task descriptions and comments** — paste or drag one in, or use the picture button, which offers the camera on the app. A picture you take back out, or never save, is deleted, and so is every picture on something that's deleted for good. Images from other websites in comments still show as links.
- **Smaller additions** — a 12- or 24-hour clock under **My Settings → Interface**, a **Fields** menu that picks what kanban cards show, a file upload in **Add link**, a colour for each priority, and MCP assistants can now tick checklist items.
- **For operators** — `/api/v1/metrics` serves Prometheus metrics when `METRICS_TOKEN` is set. Communities can be put **On hold**; one left on hold for 30 days is deleted, and its superadmins are emailed that date when the hold starts. Change the window under **Settings → Platform → Community**. **Settings → Intake** takes contact addresses, which notices use when they tell people who to contact. Sign-in placement rules on an identity provider add people to communities by group.

### Changed

- **Apps appear where they are placed** — an app placed in "every initiative" is placed in each initiative that exists when you save, and an initiative created later does not get it until you add it under **Community settings → Integrations**. Apps your deployment requires are still added to new initiatives, and can be removed from any one of them.
- **Exporting a tool belongs to whoever can delete it** — export moved to each tool's **Settings → Advanced**, for its owner, community admins and roles with full access. Every tool can be exported there. Galleries download as a zip with their pictures, and wikis as PDF, Markdown, Word or an importable zip that brings their filed documents along; both zips import back.
- **Suspension means no access** — a suspended community or account reaches nothing, settings included, until the suspension is lifted, and sees a notice saying who to contact. Nothing is deleted.
- **Imports live with the community** — Todoist, TickTick and Vikunja imports moved from **My Settings** to **Community settings → Data**. They now bring due dates, tags, assignees and comments along.
- **Sign-in group rules are set per community** — they moved from platform settings to **Community settings → Security**. Rules that were already saved keep working.
- **Signing out affects only the device you're on.** Changing your password still signs out everywhere.
- **Names and titles are capped at 255 characters.**
- **One database URL** — set `DATABASE_URL` to the database owner and Initiative creates its own database logins, with passwords derived from `SECRET_KEY`. Existing setups that set `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` work unchanged. To switch, point `DATABASE_URL` at the owner, remove `DATABASE_URL_APP`, `DATABASE_URL_ADMIN` and `DATABASE_URL_BOOTSTRAP`, and restart.
- **Breaking API and configuration changes**
  - `/api/v1/admin/*` is now `/api/v1/operator/*`, and `/api/v1/announcements/admin/*` is now `/api/v1/announcements/operator/*`. The matching `Admin*` schemas are renamed `Operator*`.
  - `/api/v1/settings/oidc-mappings` and the operator routes for initiative and community members were removed. Use `PATCH /api/v1/guilds/{guild_id}/members/{user_id}` and `/api/v1/guilds/{guild_id}/auth/rules` instead.
  - The access-grant approval queue is now `GET /api/v1/access-grants/queue`.
  - `CAPTCHA_*` and `FCM_*` are read on first boot only. After that, set the captcha in **Settings → Platform → Security** and push notifications in **Settings → Platform → Push notifications**, with no restart.
  - The `PAM_*_MINUTES` variables are no longer read. Access grants now last up to 4 hours for support, 8 for moderators, 24 for operators and owners, and 4 for break-glass.
  - `GET /exports/{project,document,queue,counter-group,dashboard,calendar}` answer `403 EXPORT_OWNER_REQUIRED` unless the caller holds the owner rung on every selected item. `/exports/calendar` without ids includes only calendars the caller may export. `GET /exports/post`, `/exports/wiki` and `/exports/gallery` are new; `/exports/gallery` returns a zip, and `/exports/wiki` takes `pdf`, `md` and `docx` and always returns a zip with the wiki's filed documents. `POST /imports/envelope/archive` imports an export zipped with its files.

### Fixed

- Initiative members who aren't community admins can upload documents again.
- Emailed sign-in codes work on servers that use a captcha.
- Support and break-glass grants now open the settings they were granted for. Settings you can only view are shown as view-only.
- An edit made just before you leave a document now shows up in exports, search and wikis. Columns survive the Markdown view and exports.
- Every kind of document opens properly inside a wiki.
- Sign-in group rules place only people the community's own connection recognises.
- On servers that keep files in S3, backup restores and large imports finish instead of failing when they are applied.
- A restored backup, or a single exported project, document, post or wiki, now links its mentions, `#` references, `[[ ]]` links and smart chips to the right people and things. A reference to something the backup didn't carry keeps pointing at the original in the community it came from, and is its name anywhere else.
- `#` references to wiki pages, counter groups and other two-word tools in comments now count in **Linked from**.
- A deleted account is now emptied completely. Its trophies, installed decoration packs, custom status, passkeys, notifications and queued email go, along with its direct-message devices, contacts, favourites and ignores. Operators can now permanently remove an account that once set a community's icon or banner.
- Deleting or anonymizing an account no longer fails when it was mentioned in archived work or in a comment in the trash.
- Making a missing tool from `[[` in a comment now puts the link where you typed it, and works in replies too.
- Other fixes: task table columns no longer jump while scrolling, tags shorten to fit the space they have, export formats show their names, broken and missing pages get a proper error page, restored backups keep comment replies in their threads, imports ask about everyone they mention, and access-request notifications open the right page.

## [0.71.3] - 2026-09-21

### Added

- **A deployment can be told its ways in before anybody signs in** — `AUTH_LOGIN_METHODS=sso,passkey,totp,email_otp` in the environment seeds **Settings → Platform → Authentication** on the first boot, the way `OIDC_*` seeds the provider, so a server meant to run without passwords never has them on. Read once, when the settings row is first created; after that the page owns it and the variable is ignored. A value this version does not know is dropped with a line in the log, and a list with nothing that can begin a session — or one asking for the emailed code with no mail server configured — keeps the default.

### Changed

- **Trophies say who you are, not what you're holding** — most were named for the object drawn on them: Backpack, Tent, Bat, Cat, Cup. Renamed across sixteen packs — Books, Cinema, Drama, Education, Gaming, Nature, Observatory, Pets, Soundcheck, Spooky, Sports, Tea, Travel, Winter, Zen and Plants — to say what they mean instead: a backpack is now **Hiker**, a tent is **Camping fanatic**, a bat is **A little batty**, a cat is **Cat person**. Faith, disability, family, First Nations, heritage, Pride and the country flags were left alone — those already say exactly what they are.

### Fixed

- **Webhook delivery no longer pins the database on a busy community** — every five seconds, for every subscription, the poller scanned the whole change log under that subscription's owner, putting each row through the membership check before anything cheaper got a look. On a community with a few thousand logged changes and a handful of subscriptions, a pass took seconds per subscription and the database sat at its CPU limit doing nothing else. The scan that finds which transactions are still owed now runs as the system, reading only the ids and the ledger's settled-or-leased columns; what a subscription's owner may see of each transaction is still decided by the same visibility rules, on the handful of rows that transaction holds. One consequence: a change the owner could not see when it was written is settled as empty for them rather than held back until they gain access to it later.
- **A webhook target that never comes back stops being retried forever** — a subscription whose delivery kept failing was retried on an hourly schedule with no end, holding every later change behind it indefinitely. A batch now gives up once its retry schedule is exhausted, and the changes queued behind it are delivered instead of waiting on one that will never succeed. Every subscription's read now also reports `dead_letter_count`, so a target that has been failing shows up instead of retrying silently with nothing to see.
- **The Pride pack's hearts are hearts again** — Pride, Non-binary, Trans, Lesbian, Gay, Bisexual, Asexual and Polyamorous each wear a heart trophy whose two lobes were drawn with an arc too tight to reach around itself. Browsers correct that by flattening it, so the top came out as two straight ridges meeting at a shallow notch instead of a rounded heart. The outline is redrawn with real curves, and the striped fill inside it follows the same line.
- **A couple of corners still said "guild"** — the phrase a community's Danger Zone tab asks you to type to confirm deletion, and the name the calendar app installs under, hadn't caught up with the rest of the app's move to "community." Confirming deletion now asks for `DELETE COMMUNITY <NAME>`, and the app installs as "Community calendar."

## [0.71.2] - 2026-09-21

### Fixed

- **Upgrading to 0.71.1 no longer stops at startup** — on a server that had ever trashed, archived or purged one of the shared calendars created for it last month, 0.71.1 refused to start: the repair it carried for those calendars' ownership was blocked by the same rule that keeps trashed and archived content read-only, and the server tried the upgrade again on every restart. Nothing was changed on such a server — the upgrade stepped back each time — so 0.71.0 runs against it as before. The repair now sets that rule aside for the one statement and puts it back after, and a failure inside it would name its real cause instead of the aftermath. If 0.71.1 started for you, it did the same thing this does and there is nothing further to run.

## [0.71.1] - 2026-09-21

### Added

- **A person's name is the way to them** — a mention of somebody in a comment or a document was a badge and nothing more, and the name over a comment was plain text. Both now open that person's profile, and pointing at either one shows a card with the banner they are wearing, what they said they're up to, their trophies and when they joined. A mention also shows who that id is *now* rather than the name it was written with, so somebody who changes their name is renamed in every sentence that mentions them, in every comment and document, with none of them edited.
- **Pictures zoom** — a picture opened full screen can now be zoomed: pinch it on a phone, double-tap to jump in and back out, hold Ctrl and scroll on a trackpad, or use the two buttons in the top bar and the `+`, `-` and `0` keys. While it is larger than the screen a drag moves the picture around instead of turning the page, and it never travels further than there is picture to bring back. Letting go, or moving on to the next one, starts again at fit-to-screen. This is the same viewer the gallery, a document's attached image and an announcement all use, so all three gained it at once.

### Changed

- **A checklist line too long to read can be opened** — a step with more to say than the row could hold ran off the end of its field with no way to see the rest of it. A line that does not fit now carries a chevron that opens it to its full height, closes it again, and is absent from every line that fits. An opened line is still editable, and still saves the same way.
- **A task's description opens as it reads** — the description field started on the writing tab, so arriving at a task meant looking at its markdown rather than at the task. It now opens showing the finished text, with **Write** a click away and the tab you pick staying picked. A task with nothing written yet still opens ready to type.
- **The mark on a blocked task is a caution** — something waiting on another piece of work is a thing to know about, not a thing that has gone wrong, so the mark on its board card and in every task table is now amber rather than the grey it shared with everything else.
- **A document card no longer counts its projects** — the card carried a badge saying how many projects a document was attached to, which was a number almost nobody needed and the one badge that showed up even when the answer was none. The links panel on the document itself says what it is attached to.

### Fixed

- **Content nobody owns can be claimed again** — a community's older shared calendars were listed under **Settings → Users** as having no owner, and claiming them came back with a server error every time. Ownership of those calendars had been recorded against a role rather than a person when they were first created, which is not something the app can hand to anybody, and the sharing panel never showed it either. Those roles now hold ordinary edit access, listed where the rest of a calendar's sharing is, and the calendars can be claimed like everything else on that list.
- **A server reached at its own address works again** — on a deployment reached over plain HTTP at a name or address other than the one set as `APP_URL` — a NAS, a box on the house network — ticking a checklist item, saving a change or opening anything live came back with “This request didn’t come from a page on this site”. Browsers only send the header that proves a request came from the page in front of you when the address is HTTPS or localhost, so there was nothing to read and the address people had typed was not the one configured. Such a request is now settled by comparing the page it came from against the address it was sent to, which needs no header and no configuration: a community reached at whatever address its server answers on writes, and its live views connect, without anybody editing a setting first.
- **The notification panel fits the window** — it reserved the same tall box whether it held twenty notifications or two, and on a short window the bottom of it ran off the screen where the **See all** button could not be reached. It is now as tall as what is in it, and never taller than the space it has, with the list scrolling inside while the heading and the footer stay put.

## [0.71.0] - 2026-09-20

### Added

- **A server can say how long a session may sit untouched** — it could already set the longest anybody may stay signed in, but how long a session could be left alone was fixed when the server was deployed and changeable only by editing configuration and restarting. **Settings → Platform → Security** now asks for both. Leave it blank to keep the deployed window. Using the app counts as touching it, so the clock only runs down once somebody has stopped, and a community held to the twelve-hour standard still shortens it further for its own members — whichever is strictest wins.
- **Sign-in is the deployment's to configure** — **Settings → Platform → Authentication** now lists passwords, single sign-on, passkeys, authenticator codes and a six-digit code sent to your email, with a tick beside each; the last one standing cannot be withdrawn, and a change that would leave accounts with no way in says how many first. The email code is new and off until you turn it on: type your address, read the code out of your inbox, and you are in, and the same box makes an account for somebody who does not have one yet. An account can now be made with a passkey and no password at all, and emergency access takes a passkey too. **Settings → Platform → Security** can require a second factor of everybody with a platform role or of everybody with an account — an app, a passkey or a single sign-on that did the second factor all count, nobody is signed out, and the page says how many people it covers before you save; personal API keys and the app on a phone stop working for those people until they set one up. The setup wizard knows Salesforce, JumpCloud and Dex by name now. And where the operator grants it, a community can run its own: **Settings → Community → Security** says which of the deployment's providers count as its own and whose accounts on them are theirs, places people by the groups its provider reports, requires arrival through one of them with a second factor alongside, refuses personal API keys and shortens sessions — all without ever seeing an address, client or secret.
- **You choose when email reaches you** — **User settings → Notifications** now asks how often, not just whether: right away, hourly, daily at a time you pick, or weekly on a day you pick. Anything held arrives as one message grouped by community, minus whatever you read in the app, and things another person addressed to you skip the queue unless you say otherwise. You can pause email and mobile across a date range, booked ahead or starting now, and nothing interrupts you while the app is open in front of you. Overdue task reminders ride the same schedule instead of their own daily clock, and quiet hours now deliver the mail they held rather than a line counting it.
- **Every tool says what it is connected to** — calendars and their events, counter groups and counters, dashboards, galleries and their pictures, notices and queues all carry the links panel now, named for what it sits on, with headings in plain English: **Blocking**, **Made up of**, **Mentioned in**. Adding one starts from the search box rather than a dropdown of phrases and reads back as a sentence — **This task** *is blocked by* **Order the marquee** — with every row naming the project, wiki, calendar or queue the thing sits in and what it is currently doing: a task's column, an event's date, a counter against its target, a project as the work in it (**1 / 3**). A blocked task carries a mark on its board card and in every task table, counting only what is unfinished, so it clears itself when the last blocker is done.
- **Exports carry the whole community** — the settings, the tags and their colours, who was a member and at what role, which apps were installed, each initiative's roles and property definitions, dashboards, and files nothing currently points at, all in a `guild/` folder beside the initiatives, and all of it comes back on import. A dashboard built on an installed app is listed as skipped rather than passed over in silence. The archive is written to disk as it is produced, so the ceilings are an order of magnitude higher — half a million records and 10 GB of files — and past about 2 GB it is delivered to a folder the administrator has set up rather than offered as a download. The export screen says which will happen before you start.
- **An assistant can find a thing by its name** — an assistant connected over MCP can now run the same search the app's own search page runs, ranked across every tool, comments and tags. It answers under your permissions, so it finds what you would find and nothing else.
- **A community asking for twelve-hour sign-ins now also ends a session left alone** — twelve hours was the longest a session could last, with nothing saying how long it could sit untouched, which is only half of what the automatic-logoff standards these communities follow actually ask for. The same switch now ends a session after fifteen idle minutes. Using the app counts as touching it, so the clock only runs down once somebody has really stopped; what they meet on returning is the sign-in page. Nothing changes for anybody outside such a community.
- **Deleting your account now sends a receipt** — the deletion happened and nothing said so, which is the one moment somebody most wants written confirmation. Every address you had confirmed gets a short note saying the account and the personal information held with it are gone, and that what you contributed to a community stays there under a deleted account. If your server can't send email the deletion still happens, quietly, as before.
- **An import asks who its people are before it writes their words down** — dropping an exported project on a board imported its comments straight away, and anybody the file quoted who was not already a member here lost their account: the words landed under their old name, with no face and no profile. The file now stops and asks who each of them is on this server, listing how many comments each wrote — the step a whole-community restore already had. Exact matches are filled in, and leaving a row blank is a real answer: those comments keep the name they arrived with. It only asks when there is something to ask, so a file quoting nobody still imports on one click. Your answers decide who a task is assigned to as well, though an assignment still only lands on somebody who is in the initiative it is going into.
- **Notices can be imported from the board that lists them** — every other tool's list page took an exported file; the bulletin board did not, so a notice's own export had nowhere in the app to go back in. Its overflow menu now offers the import like the rest of them.
- **A deployment can ask arriving visitors about cookies** — a chooser along the bottom of the page the first time somebody lands, saying what is essential and has no alternative, with a switch for anything that isn't. **You are only asked about what your deployment actually uses**: a server your group runs for itself has no analytics or marketing configured, so it asks about neither and simply says what is kept. Where there is something to decide, **Reject optional** and **Accept all** sit side by side at the same size, and everything optional stays off until it is switched on, so ignoring the question grants nothing. The chooser is off until a platform owner turns it on under **Settings → Platform → Branding**, which suits a server with a public front door and leaves one a group reaches by invitation alone. Your answer is kept in the browser you gave it in, and once you're signed in it follows your account too — a new browser or phone takes it rather than asking again, and changing your mind on one reaches the others. Answered before signing in, it stays in that browser and goes nowhere. The landing page's footer and **User settings → Privacy** both reopen the chooser. Where an administrator has configured a sign-up spam check, it names the company behind it.


### Changed

- **Claiming a domain now has to be agreed** — a community says which arrivals on a sign-in provider are its people by naming a claim and the values that count, and it names those itself: nothing in the app can tell whether it holds the domain or workspace it wrote down. Those values are now agreed by whoever runs the server before matching arrivals are joined on sight — as a support request where the server takes them, and on the community's own page under **Settings → Admin → Communities → Manage** either way. Until then the connection still works for the people already there, and joining is by invitation. Changing the values asks again. Anything already set up keeps working.
- **A community can ask its members for a second factor** — the box was nested inside the sign-in requirement, so it could only be reached by a community that also required single sign-on, and choosing “anyone may arrive however they like” threw it away. It is now its own switch under **Settings → Community → Security**, beside API access and session length, and independent of how people arrive. The community asks; which kinds of factor count is the server's answer, not theirs. Anything already required is carried over.
- **A provider says whether its word counts for a second factor** — an identity provider that reports having run one satisfied a requirement for a second factor automatically, on any provider, which is a judgement about that provider rather than a fact. **Settings → Platform → Authentication** now asks, per provider, and the setup wizard ticks it for Entra, Okta and Auth0, whose products document the claim. Off everywhere else, including on upgrade: people signing in through those providers are asked for a factor of their own, which they can add without signing out.
- **Help requests can only be switched on once there is somewhere to send them** — the operator's per-community **Help requests** switch offered a community's members a form even where the deployment had bound no support stream, so anything written in it had nowhere to land. The switch is now held until **Settings → Admin → Intake** routes support into a project, and says so where it sits. Turning it off is unaffected.
- **Moving a whole community's data belongs to the superadmin** — the **Data** tab exports every initiative in one file and restores a backup zip over the top, and it was offered to any community admin. It is now the seat's alone, the way the danger zone is. Exporting or importing a single initiative, project, document or spreadsheet is unchanged and stays where it is.
- **A community says who on a sign-in provider counts as its own** — connecting a community to one of the server's providers used to allow leaving that blank, which counted everybody the provider vouched for. On a provider open to the world that is the world, and with auto-join on it placed them. Saying who is now part of connecting: pick Google and it asks for the Workspace domain, Microsoft and it asks for the tenant, and anything else can be named directly. A connection that names nobody admits nobody. **Setting up a connection is also one flow now** — the page offered two, a guided wizard and a shorter form beside it, which is why it asked which provider twice.
- **Only a community's superadmin can delete it, and they get a receipt when they do** — deleting a community was something any admin could do, and nobody was told it had happened. It is now the seat's alone: the Danger zone tab is not offered to an ordinary admin and the server refuses them. Whoever holds the seat gets a note afterwards saying it is gone, that nothing has been destroyed yet, and the date until which the server's administrator can put it back exactly as it was. Members get no mail — it leaving their list is the thing they can act on. If the server can't send email the deletion still happens, quietly, as before.
- **Two-factor authentication lists both ways of answering it, and the requirement greys out when neither is offered** — the section showed only the authenticator app, so a passkey answering the same question was invisible, and the setting for who must hold a factor could be filled in on a server where nothing could answer it. Passkeys now appear beside the app, marked as decided under **Ways in** since that is where they are turned on, and the requirement is unavailable with a line saying what to permit first.
- **The platform roster no longer shows addresses** — the account list under **Settings → Platform → Users** carried a shortened email column, and the reset-password prompt quoted an address back. Neither is needed to do the job: an account is found by handle, and every action on it is addressed by account rather than by address. The column is gone and those prompts name the handle.
- **Two-factor authentication moved to Security, and is called that** — it sat in **Ways in** as "Authenticator app", beside passwords and single sign-on, which put it with the things that start a sign-in. It doesn't start one; it accompanies one. It now sits on **Settings → Platform → Security** directly above the setting that decides who has to hold one, so offering it and requiring it are one question in one place.
- **The setting for what new accounts allow is nested under messaging, and greys out with it** — it sat on its own below, so a server with messaging off still appeared to be asking which starting policy those messages should use.
- **Deleting no longer destroys on the spot** — an account you delete still disappears for everyone else immediately, and now nothing is erased for thirty days: signing in during that time calls the whole thing off, with your communities, roles and documents exactly where you left them. A deleted community is the same for ninety days, restorable by a platform operator from **Settings → Platform → Communities**, which asks what it comes back as and, where nobody is left who can run it, who takes it over. Both windows belong to whoever runs the server, and leaving one blank means nothing is erased on a timer. Deactivating is untouched. A community's connections to installed apps are the one thing that does not come back, because it is the community that authorised them.
- **The age question belongs to the community, not the whole platform, and the minimum is now 16** — it used to hold the whole app behind it; it now stands in front of one thing, joining a community anyone signed in can find, and a community that has not listed itself asks nobody. Where nobody is at a keyboard to be asked, such as a group rule from your identity provider, an account that has never been asked is let in and one that answered under the minimum is not. A community holding somebody under 16 cannot list itself where anyone can find it, checked when it goes on the shelf rather than on every edit.
- **Whole-community exports have a waiting period, and the page shows where you are in it** — one every couple of days rather than on demand, counted across the community so a second administrator does not get a fresh turn. The **Data** tab now says who took the last one, how it ended, whether its file is still there to download and for how long, and when the next one can start, instead of leaving the next person to discover it by being turned away. Exports of a single initiative, project or document are unaffected. On S3-compatible storage a finished export can come from the store itself rather than through the application, once you turn on `EXPORT_PRESIGNED_DOWNLOADS` and your bucket allows the app's origin.
- **How much the server logs, and how much of it Docker keeps** — a new `LOG_LEVEL` setting governs the application's own logging, `INFO` unless you say otherwise, and the example compose file caps a container's output at 50 MB across five files instead of letting it grow until somebody goes looking for the disk space. Deployed from an earlier copy, the same four lines under each service bring yours in line.
- **A community's settings tabs** — Authentication becomes **Security**, in two sections, *Who gets in* and *On what terms*; AI and Apps become one **Integrations** tab.
- **Any tool's list can be filtered by tag** — the picker was offered for wikis alone, and the other lists ignored a tag if one was sent. Queues, counter groups, dashboards and galleries take it now.

### Removed

- **Addresses the app stopped using no longer forward** — `/tasks`, `/projects`, `/documents`, `/initiatives`, `/contacts`, `/settings` and a community's `/i` and `/settings/export`. A bookmark on one of them now finds nothing; every one of those pages is reachable from the sidebar where it lives.
- **Uploads are no longer relocated on the way up** — upgrading from **0.53.1 or earlier** now needs one stop at any release from 0.53.2 to 0.70.1 first, so that one-time move into per-community folders still happens. From 0.53.2 onwards there is nothing to do.
- **There is no longer a way to put off making the database logins** — the setting that let a server keep booting past the superuser refusal is gone, so one still relying on it needs its three logins made before it upgrades. The refusal spells out both ways: set `DATABASE_URL_BOOTSTRAP` and let the app create them on the next start, or run `python -m app.db.bootstrap --print-sql` and apply the SQL as the database owner.

### Fixed

- **Sidebar counts leave archived items out** — every tool now counts what is on its board, the way projects already did.
- **A phone that signed in with a passkey now counts as having signed in with one** — the app was handed a credential that said nothing about how you got it, so a community that requires a passkey turned you away and told you to open a browser. It travels once, with that sign-in: an app coming back days later on a credential it has been keeping is asked for a key.
- **PDFs render the way they were scanned** — the viewer moved to pdf.js 6, and the modules that decode what scanners and fax machines produce now ship with the app, so a scan draws rather than coming up blank and nothing reaches for the internet on a deployment that has none. A document mixing single pages with double-page spreads no longer blows every page up to the widest one's width.
- **Pictures and files could stop loading on a shared network** — community images and uploaded files are allowed a far higher request rate than the rest of the app, and that allowance was being passed over in favour of the general one. Each route is now held to the rate it was given.
- **A status can be deleted while archived or trashed tasks sit in it** — deleting a column holding an archived task was refused with a message about the *status* being archived, and one whose only tasks were in the trash failed outright. Those tasks now move with the live ones and keep their state where they land.
- **A restored backup kept the work and lost the record of it** — a backup now carries when each task and wiki page was written and last touched, what was said on each task, and the links between tasks, and a restore puts all of it back. Imported comments go to the person who wrote them: the wizard has a step where you check the matches and say who the rest are, and anybody left unmatched keeps the name they arrived with rather than being credited to whoever ran the import.
- **Signing in no longer lands you in somebody else's community** — a browser remembered one community for everybody who used it, and a sign-in resumed whatever page it was last interrupted on, whoever that was. Each account now keeps its own last community, and a page inside a community is only resumed for somebody who is in it. Signing in after being interrupted still takes you back where you were headed.

## [0.70.1] - 2026-09-19

### Fixed

- **Upgrading from 0.69 with OIDC claim rules no longer fails at startup** — the 0.70.0 migration that gives every claim rule and synced membership its provider read those tables in a mode that showed it nothing, so on any deployment that had a rule it skipped the backfill and then stopped on the empty column, restarting until rolled back. The database was left untouched at the previous step, and the same migration now carries every rule and membership over. A deployment stuck on 0.70.0 upgrades cleanly to this release.
- **Relations between tasks now survive a template** — a task marked as blocked by, part of, or related to another task in a project template carries that relation into the project made from it, pointing at the new project's own tasks. Duplicating a project keeps its task relations the same way.

## [0.70.0] - 2026-09-19

### Added

- **Wikis** — a new tool for what a team knows, rather than what it's working on. A wiki takes the whole screen and its pages take over the sidebar. Pages nest: drag one onto another to file it underneath. They're written in the same editor as a document, by several people at once, so `[[ ]]` links and the `#` picker work as they do everywhere else. Each page shows what it links to and what links back, carries its own comment thread, and starts as a draft only the wiki's writers can see until you press **Publish**. Documents you already have can be added to a wiki without being moved or copied. Turn the tool on per initiative under **Settings → Tools**.
- **Passkeys** — sign in with your phone, laptop or password manager instead of a password. Register one under **User settings → Security → Passkeys**, then use **Sign in with a passkey** on the sign-in screen; most browsers will also offer yours in the email box. Once you have a passkey, the password is optional — **User settings → Account → Remove password** takes it away, hands you recovery codes and signs your other devices out. A recovery code gets you back in if you lose the passkey.
- **Two-factor authentication** — set up an authenticator app under **User settings → Security**, and signing in asks for a code as well, in the browser and the app both. You get ten recovery codes, shown once, good for one sign-in each. Lose the phone and the codes and whoever runs your deployment can clear the factor so you can start over. Nobody is asked for anything until they turn it on.
- **Group direct messages** — **Start a conversation** now gathers several people instead of just one. Everyone named is asked rather than added: they see who else is on it before answering, and nothing reaches them until they accept. You can leave a group, and be asked back. Messages stay end-to-end encrypted.
- **Report a comment, post, picture or profile** — **Report** now sits on comments, notices, pictures, profiles and directory listings, and routes itself: anything a community holds goes to that community's moderators, anything about an account goes to whoever runs the deployment. Moderators get a **Moderation** entry at the top of their initiative. Private conversations are not moderated and carry no Report action.
- **Comments show you a preview before you post** — comments and task descriptions now share one composer with **Write** and **Preview** tabs and buttons for the formatting nobody remembers, plus ⌘B, ⌘I and ⌘E. Lists carry on by themselves: Enter under a bullet starts the next one, Enter on an empty one ends the list.
- **Creating an initiative walks you through it** — four steps instead of one form with the important part folded into an *Advanced* accordion: what it's called, what it's made of, who can get in, and what an ordinary member can do. The tools step is a grid, and it won't let you build an initiative with nothing in it. New communities now start with no initiative at all and ask you to name the first one, instead of handing you a folder called *Default Initiative*.
- **Backups carry wikis and galleries** — the two things hardest to retype were the two a backup left out. Both now export and import, and both can be handed to another initiative. A wiki arrives with its pages still nested, its drafts still drafts and its home page still home; a gallery arrives with its pictures rather than a list of their names.
- **The sidebar is as wide as you want it** — drag its edge to resize, double-click to put it back. It never goes narrower than it is today and never takes more than half the window. The width is kept per device, so a laptop and a desktop each remember their own.
- **Ask for help, from the sidebar** — the question mark now says **Ask for help** and opens the FAQ, or a request form where your deployment is taking them. It's there for everyone, not just admins.
- **An assistant can read what your work is connected to** — the Relations panel records what a task blocks and what belongs to what, and an assistant connected over MCP could see none of it. It can now read those links and draw one, which it asks you to confirm. Unlinking stays in the app.
- **An assistant can read and write a wiki** — wikis were the one tool an assistant connected over MCP couldn't see at all, so asking it about something the team had already written down came back with nothing. It can now read a wiki, its page tree, a page and what links to that page, and it can start a page and edit one, asking you to confirm each change. Filing a page elsewhere in the tree, and deleting one, stay jobs for a person.
- **A landing page for the person who was sent a link** — it used to talk to gamers about parties and quests. It now leads with signing in, shows what each tool is for, and puts your own device first under **Get the app**.
- **Operators choose which sign-in methods the deployment permits** — passwords, single sign-on, authenticator apps and passkeys are each a tick under **Settings → Platform → Authentication**. At least one that can start a sign-in stays on. Where accounts rely on only one method, the page says how many before you withdraw it.
- **Operators set how long people stay signed in** — a session used to end only after a month unused, so anyone using the app daily stayed signed in indefinitely. **Settings → Platform → Security** takes a maximum in hours; blank means no limit. It reaches phones immediately, while people signed in on the web keep the terms they signed in under.
- **Operators can configure a sign-in provider once for the whole deployment** — where every community would otherwise set up the same identity provider separately, **Settings → Platform → Authentication** now takes that answer once per provider and every community inherits it.
- **Operators can turn off direct messages** — a switch under **Settings → Platform → Community** removes My Messages along with the **Message** and **Connect** buttons. Nothing is deleted: turn it back on and people have their threads again.
- **One Manage panel per community** — the operator's Guilds tab had caps and switches squeezed into table columns. Each community now has **Manage**, grouping its settings into Limits, Sign-in and Features, and the table goes back to being a table.

### Changed

- **Communities have a superadmin** — running a community day to day and deciding who may get into it or what it's billed for are different jobs, and there's now a seat for the second. Whoever starts a community holds it and can pass it on; every admin a community has today becomes one, so nobody loses anything. Every community keeps at least one — its last superadmin can't be demoted, removed, leave or close their account, unless they're the only member. That replaces the old "last admin" rule, so an ordinary admin can now leave whenever they like.
- **New projects start with three columns** — **To Do → In Progress → Done**, instead of **Backlog → In Progress → Blocked → Done**. Blocked was a hangover (what a task waits on is a relation now) and most people read Backlog as To Do anyway. Deleting a column with tasks in it no longer demands a replacement in the same stage — pick any column, or leave it and the tasks fall to the project's default. Existing projects keep the columns they have.
- **Projects and documents can be switched off** — they were the two tools every initiative had whether it wanted them or not. Both now have a switch under **Initiative settings → Tools**, so a book club can be documents and a calendar with no empty Projects tab. Existing initiatives keep both, and new ones still start with both.
- **The roles screen shows what you can actually change** — Project Manager used to render sixteen switches pinned on that refused every click; it says so in a sentence now. The rest is one row per tool with View and Create together, and granting Create grants View with it.
- **Joining sits with the roster** — how people get into an initiative has moved from the Details tab to **Initiative settings → Members**, above the roster and under the requests waiting on it. Details keeps the name, description, colour and tools.
- **Document and spreadsheet toolbars fit the pane, not the window** — both used to swap layouts at a screen width, so a document beside the sidebar got the narrow toolbar on a wide monitor and the spreadsheet's wrapped into three rows. Both are now one row that measures the space it has, shedding controls into a **⋯** menu that names them.
- **The app on your phone renews its session** — mobile sign-in used to hand the app one credential good for months. It now gets a session of the same kind the browser has, renewed in the background. You're moved across automatically; nobody has to sign in again.
- **The Admin dashboard is now the Operator dashboard** — "admin" is the word a community has already spent, and nothing on that screen belongs to one. The users table also dropped the column carrying everybody's real name; each row now has **Manage**, holding what there is to decide about one account, and offers only the controls your own permission covers.
- **Platform settings gain a Security tab, and AI and App services merge** — session length moved from **Authentication** to a new **Security** tab beside it; the sign-in methods and the provider registry stay where they were. **AI** and **App services** are now one **Integrations** tab.
- **Staff reach a community through a scoped grant** — someone holding the platform's highest permission could break glass into a community and land as a full admin of it, with none of the limits an ordinary support grant carries. A grant now says what it reaches, and that's what it reaches, whoever holds it. Access to a community's settings is its own kind of grant, asked for alongside access to the content or instead of it, so somebody helping with a billing question gets the billing screen and nobody's documents. Breaking glass still exists for emergencies, and every request, decision and self-issue is written to the audit log.

### Fixed

- **Signing in through a provider whose address ends in a slash** — every attempt was refused and no combination of settings helped: the address was trimmed of its trailing slash on our side, then matched against the untrimmed one the provider itself sends, so the two never agreed. Authentik is the common case.
- **The MCP address works with or without a trailing slash** — pointing an assistant at `…/api/v1/mcp` returned Not Found unless the address ended in a slash, and several clients save it without one — including connectors added in the browser, which give you no way to see why.
- **Every direct message tells you it arrived** — a conversation announced its first message and then went silent: replies never reached your phone and the bell kept counting up without clearing. Your phone now buzzes for every message, and reading one anywhere clears it everywhere.
- **Restoring from the trash brings back what's archived inside** — restoring an initiative was refused whenever anything inside it had been archived first.
- **Importing a calendar file** — every .ics file came back unreadable, so **Import Calendar Events** couldn't import anything at all.
- **Comments on notices and galleries reach the activity feed** — a comment on one was filed without a community, so the feed skipped it. The thread itself read back correctly; the comment just never appeared anywhere else. Existing comments are repaired on upgrade.
- **Saving a renamed document while others are editing it** — the Save button and Ctrl+S were refused with "This document is being edited live", though the same rename went through on its own moments later.
- **Opening a task in another project** — following a relation left the Status field blank, then refused to let you leave without saving and refused the save for want of a status.
- **A community's name no longer runs under its member count** — on a community with no banner artwork, a long enough name at a narrow enough width wrapped underneath the counts.
- **Platform role changes are written to the audit log** — suspending, renaming and removing a picture were all recorded; moving somebody up or down the platform ladder was not.

### Security

- Updated `anyio` to 4.14.2 for CVE-2026-63374, a host name encoding issue in its TLS stream that could let a certificate be matched against the wrong name.

## [0.69.0] - 2026-09-14

**Nice.**

### Added

- **Your account holds as many email addresses as you need** — an account was one address, so the one you signed up with was the one you were stuck with: changing jobs, losing a mailbox or wanting work and personal mail kept apart all meant asking somebody. **Settings → Account** now lists every address on your account and lets you add another. We write to a new one with a link, and until you follow that link it does nothing — then it signs you in like any other, and account mail reaches all of them, so a password reset lands somewhere you can still read. One address is the primary: it is where a community sees you, and you can move it to any confirmed address. The one you came in on is not special, but the account always keeps at least one confirmed address and a primary, so you always have a way back in.
- **Anything can be connected to anything** — a project could hold documents, a queue item could hold documents and tasks, and nothing else could be linked to anything at all. Every one of those screens now has the same Relations panel: search once, across everything your initiative holds, and attach a document, a project, a queue, a calendar, a dashboard, a picture — whatever the link is actually about. Tasks have one too, under the checklist, and it records more than attachment: what a task is **blocked by**, what it **blocks**, what it is **part of** and what belongs to it, so a dependency is something you can write down rather than something you mention in a comment. Each link is drawn as a card showing what the thing is, with the document's own cover picture, a gallery's cover, a project's emoji or a calendar's colour, and it reads from both sides — say a task is blocked by another, and that other task shows it is blocking this one.
- **Four ways to look at what is connected** — the same panel draws its links as tiles, as a compact list, as the carousel a project's attachments have always been, or as a graph: the thing in the middle, everything it touches around it, and up to three hops further out if you ask. The graph settles itself, and you can drag a node and watch the rest move out of its way, zoom with the wheel, and click through to anything in it. Tags are left out of it unless you turn them on, because a tag is carried by everything carrying it and one hop through a popular one reaches most of a community. Each screen opens the way that suits it — a carousel on a project, a list beside a task — and remembers whichever you pick.
- **A document's connections can be changed from the document** — a document listed the projects it was attached to and could not be detached from any of them, because attaching only ever worked from the project's side. The same panel now serves both ends, and the pages that link to a document still appear there, marked as read from what those pages say rather than as something you attached.
- **A changed device key is pointed out** — when someone you message starts using a different key on a device you had already written to, the messages panel now says so and shows the pictures to compare, naming who it is about. Most often that means they replaced or reinstalled a device. A key seen for the first time is not flagged.

### Changed

- **The mobile app's framework is up to date** — Capacitor moves to 8.5.2, a patch release across the Android, iOS and core packages. No behaviour changes; it ships as a new app version because native code cannot be updated over the air.
- **A task opens from its title** — anywhere a project lists its tasks, the whole card and the whole row were one big button, so picking up a card to drag it, or reaching for something else on it, could land you on the task instead. The title is what opens a task now, on both the board and the table, and it is a real link: middle-click it, or open it in a new tab, and it behaves like every other link in the app.

- **Full access belongs to a role called Moderator** — "reaches every item in the initiative however it was shared" used to be a switch a community admin could throw on the project manager role, so it applied to every project manager at once. Every initiative now has a built-in **Moderator** role that carries it, listed first in **settings → Roles** with no tool switches to set, because it holds them all. Project managers keep every tool permission and lose the override. Only a community admin puts somebody on Moderator, and a community admin joining an initiative arrives on it, which is the standing they already had. Existing initiatives get the role on upgrade, and anyone whose project manager role had full access keeps reaching what they could reach.
- **A dashboard reports on live work** — a question asked of your tasks was answered with all of them, so a board of "who is carrying what" dealt out the steps of every template project alongside real work, and archived work counted the same as current work. New widgets now start by leaving out archived rows and templates, as ordinary filters you can see and delete when the question really is about archived work. The five dashboards that ship with the app ask the same way.

### Fixed

- **You stay signed in** — the app renews your session quietly in the background, and any stumble in that renewal was read as "your session has ended": a restart while you had a tab open, a slow moment, a network that dropped for a second. It then signed you out — everywhere, including the phone in your pocket, which had nothing to do with it. Only the server actually refusing your credential ends a session now, and when one does end it ends on the device it ended on. Two windows of the app open at once could also end the session between them, each renewing on its own and the second arriving a moment too late to be recognised as you — windows now take it in turns, so the second uses what the first renewed instead of asking again.
- **The realtime connection reconnects with a current credential** — a window open for more than about a quarter of an hour renewed its credential without telling the live connection, so if that connection dropped — a laptop sleeping, a network blinking — it came back with an out-of-date one and was turned away, retrying against a closed door for as long as the window stayed open. Cards moved by somebody else stopped appearing until a refresh. It now presents whatever credential is current at the moment it reconnects, and a connection that is genuinely not wanted stops trying instead of retrying forever.
- **`ACCESS_TOKEN_EXPIRE_MINUTES` is gone** — the setting no longer reached anything, so a deployment that set it was tuning nothing. How long people stay signed in is `AUTH_ACCESS_TTL_MINUTES` (how often the browser renews, default 15) and `AUTH_REFRESH_TTL_DAYS` (how long a session survives without the app being opened, default 30). Both were already the real defaults; nothing about how long anybody stays signed in has changed.
- **A deployment behind a reverse proxy says so in the log when it is not configured for one** — without `BEHIND_PROXY=true`, every visitor arrives as the proxy rather than themselves, which is not visible anywhere: rate limits meant per person apply to everybody at once, and every sign-in is recorded from the same address. The first request that shows it now says so once in the log, with the setting to change.
- **The phone in your pocket is told about your messages** — a direct message reached the app only while it was open on screen: every push it should have sent was thrown away before it was built. The app only sends a message notification to an installation that can actually read it, and the two records that say which installation is which were never being written, so nothing ever matched and nothing was ever sent. Both are written now, and an app that has been installed for a while repairs its own record the next time it checks for messages — so a message you are sent lands on your phone whether or not you were looking at it. Tapping the notification opens your messages, which it previously did not; it still names who wrote to you and nothing else, because the message itself is never readable outside your own devices.
- **Somebody asking to reach you is worth an interruption** — a connection request, a message request, and the answer to either, only ever reached a screen you already had open. Nobody was told, so a request sat in a list nobody had a reason to open, and whoever sent it read the silence as a no. All four now write a line in your notifications and notify your phone, subject to the same Messages preference and quiet hours as everything else. Somebody you have ignored still gets nothing through to you.
- **A new device can ask your other devices for your message history** — your messages are readable only on the devices you have signed in, so a new phone starts empty and has to be sent your history by one of your existing devices. It asked, and the ask arrived only if that other device happened to be open at that moment — otherwise it sat unread and the new phone waited forever. The ask now notifies your other devices, so you can pick one up and approve it. The notification says a device is waiting and nothing more. The banner on the waiting device can also be dismissed by hand rather than only after a day; putting it away hides the notice and nothing else, so history you approve later still arrives.
- **A notification your app does not recognise still arrives somewhere sensible** — the app is updated over the air, but the list of notification categories your phone knows about only changes when you install a new version of the app itself. A notification sent to a category your installed version had never heard of was filed by Android under a "Miscellaneous" heading of its own invention, outside the app's notification settings — so it ignored anything you had muted and you could not turn it off. Those now land under General, which is a category the app actually offers you.
- **Only the new device asks** — signing into a second browser left both of them asking each other for the history, each showing the other a code to approve, when only one of them was missing anything. A device was marked as needing history when it was set up with nothing in it, and stayed marked that way for as long as it was the only device you had — so the browser you had been using all along was still flagged as empty by the time the second one appeared. The request now only ever travels from a newer device to an older one, and the first device on an account settles the question for itself instead of holding it open.
- **Published containers include available operating-system security updates** — the final image now applies the Debian repository's current package fixes during its build instead of keeping vulnerable packages inherited from an older base-image rebuild. The build fails if any package is left behind, so the claim is checked rather than assumed.
- **The trash stays out of dashboards** — a dashboard could count deleted tasks in its figures, so the same board did not always show the same number to everybody reading it. Queries now report on live content only. The trash screen itself is unchanged.
- **"Finished, last 30 days" counts again** — the tile failed to load on all four dashboards that carry it, as did any query measuring a stretch of time.
- **A board widget with a lot of cards draws them** — a column holding more cards than fit shared its height out among them instead of scrolling, so a board of a few hundred tasks drew every card as a hairline with its title spilling over the next. Columns overflow and scroll now, at any number of cards.
- **Widget previews draw again** — the preview beside the widget settings ran the widget without telling it which of the statement's columns were which, so anything that draws numbers reported it had been given none: "No numeric column to report" over a query returning nothing but counts. A widget is handed column positions rather than names and works out neither its own shape nor any correction the author made, and the preview was the one place doing neither. It now resolves them exactly as the placed tile does, falls back to the table when a statement stops returning the shape the widget draws, and loads the widget's own code for previews of widgets that came from an app — so the pane shows what the tile will show, which is what it says it does.
- **Long dropdowns scroll again** — a menu with more options than fit on screen ran off the bottom of the window with no way to reach the rest, which is what the column picker in the dashboard query builder does on a table of any width. The height limit these menus are supposed to obey had been written in a form the styling toolchain stopped understanding when it was upgraded, so it was silently thrown away. Menus are capped to the room they have and scroll again, and the same silent loss is fixed everywhere else it had happened: the date picker's cells, the width popovers take from the control that opened them, and the direction menus and tooltips grow from when they open.
- **A dashboard's tiles all draw, however many of them ask the database** — a community may have only so many of its own queries running at once, and opening a dashboard asked for one per tile in the same instant, so a canvas of five SQL widgets drew two and told the other three there were too many requests. The page now runs them a few at a time, in the order they were placed, and a tile that is turned away because somebody else in the community is querying waits a moment and asks again instead of showing an error. A tile that is refused for any other reason — a statement that asks for too much work, one that takes too long — still says so straight away.
- **The order you put your communities in stays put** — dragging the communities in the sidebar into the order you want them showed the new order and then lost it: nothing was written down, so the next page load put them back the way they were. The order is saved now, and it is saved for you alone — it is your list, not the community's.

## [0.68.3] - 2026-09-11

### Changed

- **My Tasks stops going dark every time you tick something off** — checking a task off, or moving it to another status, put a translucent "Updating" panel over the whole table and disabled every row in it until three cross-guild requests had come back. The change now shows on the row the moment you make it, and everything else on the page stays live: you can carry on sorting, paging and checking things off while the list catches up behind a thin progress line. Only the row actually saving is held, so it can't be submitted twice, and if the save fails the row goes back to what it was and says so.
- **My Tasks loads faster** — the page used to fetch every task assigned to you, in every community you belong to, complete with its status, people, tags and properties, and then show twenty of them. It now works out the order first and loads only the rows on the page you asked for, from only the communities that have one, so the work no longer grows with the size of your task list. Your saved filters and sort are also fetched as soon as you sign in rather than when the page opens, which took a round trip out of the wait before the first row could appear.

### Fixed

- **A task opened on a phone is one column again** — the task page put its form and its checklist side by side on any narrow screen, giving each half as little as 152px on a phone and around 280px on a small tablet: a form squeezed into a third of a column nobody would choose to fill in. The two halves now sit one above the other until there is genuinely room for both at full width, which is what they already did between 640px and 824px. Wider windows are unchanged.
- **A task's title is sized like a title, not a banner** — the heading on the task page was set three steps larger than the page's own headings, so a task with a name of any length took two or three lines before anything about it was visible. It now sits at a size that leaves the task's details on the first screen.

## [0.68.2] - 2026-09-11

### Added

- **A document has a contents list** — a long page is easier to move around than to scroll, so every document now offers one: a panel listing its headings, nested the way they are written, that scrolls the page to a heading when you pick one and marks the one you are reading as you go. Sections with headings under them fold away, and a document that starts at a second-level heading is laid out from there rather than from an indent nobody wrote. It is closed until you open it, and then it stays open. Beside the document on a desktop; on a phone it takes the page over while it is open, because a column that narrow would be worse than no list at all.

### Changed

- **Signing in is written down** — the audit log kept moderator actions and nothing about authentication. Signing in, a refused sign-in and why it was refused, signing out, changing or resetting a password, an account linked to a single sign-on provider, and a replayed session token are all recorded now, with who and when. A refused attempt is recorded only when it matched a real account — an address nobody holds is not written down at all, and a refused attempt records the account it was aimed at rather than crediting that account with making it. This is the record an administrator needs to answer who got in and when, and it is what the existing audit log was built for.
- **Accounts record when their password was set** — a stored password hash said a value was there, never whether anybody knew it. Accounts created through single sign-on before mid-2026 were given a throwaway password nobody ever held, which looks exactly like a real one. Setting or changing a password now records when, so the question stops being unanswerable for every account from here on, and the few stored values that could never have worked have been cleared. Nothing is guessed: an existing password is left alone, and how you sign in does not change.

### Fixed

- **Archived work can be brought back out again** — the last release made archiving mean something everywhere but left no way out of it: an archived project offered "you need write access" where its Unarchive button used to be, and seven of the eight tools had no archive control at all and nowhere to see what had been put away. Every tool now has an Archive section in its settings that both puts it away and takes it back, and every tool list has an Archived view to find it in — documents beside their templates, calendars in the community's tool table. Anything archived along with the initiative or project above it comes back when that one does.

- **Upgrading no longer leaves the app unable to start** — on an existing deployment, the previous release's change to how archiving is recorded could not be applied, and the new version restarted into the same failure instead of coming up. Nothing was lost: the change is applied whole or not at all, so the database was left exactly as it was and the running version carried on serving throughout. Upgrading completes now, and a deployment already stuck this way recovers on its next restart with nothing to repair by hand.

- **Deleting an account clears its sign-in sessions** — anonymizing an account emptied it of everything personal except one thing: the record of where it had been signed in, which keeps a device name, a browser and an address per session. Those go now, along with the rest. Sessions that have expired or been signed out are also cleared away on a schedule after thirty days, rather than being kept indefinitely. Permanently deleting an account already removed them with the account itself.

## [0.68.1] - 2026-09-11

### Changed

- **Anything can be archived, and archiving records when** — archiving was three things: a project, a task, and an initiative. It is now every tool — documents, queues, counter groups, calendars, dashboards, notices and galleries as well — because anything a community works through can be finished with. Archiving also remembers the date now, everywhere; a project screen already showed "archived on", and a task or an initiative could only say whether. Archiving something archives what is inside it — an archived initiative puts its tools away, an archived project puts its tasks away — and bringing it back brings those back with it, while anything you had archived separately stays that way. Archiving and unarchiving moved to one action that works the same way whatever you point it at, so a saved filter that asked for "not archived" now asks whether it has an archive date, and is carried across for you on upgrade. Project export files record the date rather than the flag; an older file still imports, and a project it held as archived comes back ready to use.
- **Archived and finished work is properly read-only** — archiving a project stopped edits on a handful of screens and left the rest open; archiving an initiative only hid it from the sidebar, with everything inside still editable; an archived task could be edited as though it were not. Archiving now means what it says, everywhere: an archived initiative, project or task is read-only until you bring it back, and so is everything inside it — tasks, comments, reactions, attachments, properties and sharing alike. The trash works the same way: a trashed item and its contents can be restored or emptied, and nothing else. Deleted work is also out of sight now, not just out of the way — once something is in the trash only you, as the person who deleted it, and your community's admins can still see it. Unarchiving and restoring are unchanged, and so is reading — archived work still opens, searches and exports the way it always did.
- **"Linked from" counts what a conversation says, not just what a page says** — a document's backlinks were read from links typed into other documents' text. A `#` mention written in a comment now counts too, recorded against whatever the comment is about, so a page mentioned while discussing a project shows up under that project the way one mentioned in its body always has. What a page refers to is also kept for every kind of thing now, not only for other documents — a task or a queue named in a document is remembered as a reference to it, ready for the surfaces that will read them.

### Fixed

- **Removing a sign-in provider no longer takes accounts with it** — deleting a provider from the registry removed the links of everyone who had signed in through it. For most people that was harmless: they still had a password, or a second provider to use. For someone who had only ever signed in through that one provider, it removed the only credential their account had. Deleting a provider is now refused while any account holds it as its only way in, naming that as the reason — those people set a password or link another provider, and then it deletes. A provider some community's sign-in requirement depends on was already refused, and still is.
- **Hiding a spreadsheet row hides it** — a hidden row stopped taking up space but kept drawing its contents, which landed on top of the row beneath it: hide the row holding "Test2" and "Test2" and "Test3" ended up printed over each other on one line, with both row numbers crowded into the same place. A hidden row or column is no longer drawn at all, so the rows after it close up the way they should. Hiding a frozen row does the same.

## [0.68.0] - 2026-09-11

### Added

- **Galleries: a home for the pictures** — a new tool beside Documents and Posts for the visual half of the work: mockups, screenshots, app icons, the four logos that lost. A gallery is a named wall of pictures with its own sharing, comments and tags, browsed as a masonry, a grid, or a timeline of what arrived when — and grouped by tag, so "everything still awaiting a decision" is one click. Drop a folder onto the page to add them, tag or remove a selection together, and replace a picture with a new version while keeping the rounds it went through. Off by default per initiative, like every non-core tool.

- **Spreadsheets import CSV and Excel files again** — bring a `.csv`, `.tsv` or `.xlsx` file in from the button beside the sheet tabs and every tab it holds arrives as a new sheet, named after the file or its own tab. Nothing already open is touched, and the whole file is a single thing to undo if it was the wrong one. Values, formulas, bold and colour, borders, number and currency formats, column widths and frozen panes come across, so a sheet exported from here and brought back reads the same both ways.

### Changed

- **Webhook deliveries name a community by a reference rather than a number** — the envelope sent to a registered target carried this deployment's own row ids for the community and for the person whose change triggered it, which meant a service receiving deliveries from several communities held one value per person that meant the same person everywhere. Each subscription is now told its own name for both, given when it registers and repeated on every delivery, and unrelated to what any other subscriber is told. Existing subscriptions keep working and are given names on their next delivery; a receiver that matched on the old `guild_id` and `actor_user_id` fields should read `guild_ref` and `actor_ref`.
- **Subtasks are a task's checklist** — a subtask was a thing in its own right, with an id, an author and its own eight API routes, for what it actually held: a line of text, a tick-box and an order. It is now part of the task, and reads as what it always was. Everything it did still works — type and press Enter, tick one off, drag to reorder, ask AI for a first draft, and see "3/5 items" on the card — and two people ticking different lines of the same task no longer overwrite one another. Enter now starts the next line without reaching for the box at the bottom, backspace on an empty line removes it, and pasting a list gives you one item per line. Existing subtasks are carried across on upgrade, in order, with what was done still done. A phrase typed onto a checklist line now finds its task in search, which it never did before. Project export files carry a checklist where they used to carry subtasks, so a file exported by an earlier release no longer imports — re-export anything you were about to move.
- **Email addresses are no longer readable in the admin screens** — the platform user list, its CSV export, the access-request queue and every admin action that returned an account used to carry the whole address. They now carry a masked one (`u***1@e***m`), reduced on the server rather than in the page — a browser that was sent the real address has already given it away, whatever the screen shows. Enough survives to match a row against an address somebody has quoted at you; not enough to collect the roster's. Your own address is untouched: you still see it in full on your account screen. The list is searched by handle now, which is what identifies an account here, and the platform list gained a Handle column to match the community one.
- **A row of actions is one menu** — the platform user list could put seven buttons in its Actions column and a community's user list four, wrapping onto two lines on a laptop and putting *Remove* under the finger reaching for *Export*. Each row now has a single menu, with the destructive action set apart below a rule.
- **The admin user list sorts by any of its columns** — only the email column could be ordered. User ID, handle, name, role and status can now be too, each with the same control. Role sorts by privilege rather than by name, so members lead and owners bring up the rear instead of "owner" landing between "operator" and "support"; status sorts by how restricted an account is, bringing the ones needing attention together.

### Fixed

- **Moving to the separate database logins completes** — an install that had always connected as a single database user, following the prompt to point `DATABASE_URL` at `app_provisioner`, could be left with a handful of the app's own database functions still belonging to the old user. The next start could not update them: it logged `must be owner of function search_entry_write` and gave up on refreshing the search triggers and community schemas, once per community, on every boot from then on. The handover now moves every function the old login owns, keeping only the search match function the bootstrap maintains for itself. The by-hand script (`python -m app.db.bootstrap --print-sql`) was also missing one of the settings its own statements read, so it stopped partway on `unrecognized configuration parameter "app._bootstrap_tables"`; it now runs start to finish.
- **Sign-in hardening** — internal changes to how failed sign-ins are handled and recorded. No change to how signing in works. Tracked as T20; details are held privately until the work is complete across the estate.
- **The community user list's search box works** — it was pointed at an email column that a community roster has never had, so typing in it quietly did nothing. It searches handles.
- **Notices about your own account say what happened, and lead somewhere** — being renamed by a moderator, having a profile picture taken down, being suspended or unsuspended all arrived as "You have a new notification", clicking through to nothing. Each now says what changed — naming the handle you lost, or the reason for a suspension where one was given — and opens your account screen. These notices belong to you rather than to any one community, and the web app was discarding the destination of anything that did not name a community; the phone app had always followed it. The destination itself was also wrong — `/settings/profile` has never been a page — so notices already sent are redirected to the account screen rather than left broken.
- **Two windows on the same document stay in step** — a document open twice by the same person synced to everybody else but not to itself. Each window carried on as though the other were not there, so the two drifted apart; closing one, or a laptop sleeping long enough to drop its connection, could then roll the other back to where it stood when the second window was opened, with cells that had been filled arriving empty. The two windows are now peers like any other pair of editors: edits made in one appear in the other, closing one leaves the other's session alone, and a window that reconnects hands over whatever was done while it was away instead of losing it. Live documents are also saved every thirty seconds now, rather than only when the last window closes, so a restart or a dropped connection costs a half-minute at worst — and a document's saved text and its live state are written together from one moment, instead of each open window racing to save its own version.
- **Work written with no connection is not lost when it returns** — a document held its editing session open for about half a minute of lost connection and then gave up on it for good, with nothing to bring it back when the network returned. Anything written in the meantime lived only in that window, and the attempt to save it on reconnect was the one kind of save a document being edited by somebody else refuses. The session now waits out an outage of any length, comes back the moment the network does, and hands over everything written while it was away — merged with whatever everyone else did in the meantime, rather than written over it. Being refused access still ends the session; losing the connection no longer does.
- **An attachment you cannot open is no longer listed** — a document attached to a project, queue item or calendar event appeared in that list with an empty name when it had not been shared with you. It is left out entirely now, the way a link to something out of reach has always behaved.
- **Undo takes a paste back whole** — pasting a block of cells, or cutting one and putting it somewhere else, left nothing on the undo stack at all: the next undo reached past it and took back the edit made before, so it looked as though one stray cell had changed its mind. A paste is a single action again, and one press returns every cell it wrote — and, for a cut, returns the block it came from. Hiding a sheet can be undone now too, which it could not be while every other thing done to a sheet could.
- **Cell colours and bold survive an Excel export** — a spreadsheet exported to `.xlsx` kept the number formats it was given but quietly lost the look of individual cells: bold, fill, text colour, alignment and borders set on a cell arrived plain. Column and row formatting was always carried over, and now per-cell formatting is too.
- **Nothing points at itself** — a comment box offered the very thing it was a comment on, on every tool: a queue's thread offered that queue, a dashboard's that dashboard, and the same for projects, documents, calendars, counters, galleries, notices and tasks. Typing `#` or `[[ ]]` while writing a document or a notice offered the page being written on. Picking any of them made a link that opens the page the words are already on. None is offered now — not in a body, and not in any comment box, reply or edit. A document that already held a link to itself no longer counts itself among the pages linking to it, and the next save leaves the words and drops the link.
- **A document nobody is editing stops writing to itself** — a document open with live editing on saved itself every ten seconds whether or not anything had changed, so one left open in a tab kept moving its own "updated" time and appearing at the top of anything sorted by it. It saves when there is something to save.

## [0.67.1] - 2026-09-09

### Added

- **Sheets: find and replace, hidden rows, columns and tabs, and getting around a big one** — Ctrl+F searches the sheet and replaces one match or all of them; a right-click on a row or column header hides it, and a sheet's tab menu hides the whole tab, with a count beside the tabs to bring any of them back. A hidden line is still there — its cells hold their values and formulas still read them — it is simply out of the way, which is what a workbook wants when the working-out and the thing you hand someone are the same file. Ctrl+Arrow jumps to the edge of the data and Ctrl+End to its far corner.
- **Sheets: fifteen more functions** — MEDIAN, LARGE, SMALL, RANK, STDEV, STDEVP, VAR, VARP, COUNTBLANK, MATCH, CHOOSE, SWITCH, UPPER, SUBSTITUTE, TEXTJOIN and VALUE all work now, where they used to come back as `#NAME?`.
- **An assistant can read the rest of your work, not just the tasks** — the MCP server covered projects, tasks and initiatives, so anything asked of it was answered from tasks alone. It now reads documents, queues, counters, calendars and their events, notices and dashboards — including what a dashboard tile currently says, which is usually the fastest answer to "how is this going". It can also author and edit each of them now — a document, a queue and its items, a counter and its count, a calendar event, a notice, a dashboard — where it could previously only create a task, edit one, move one and add a comment. Every write still asks you first, and every call goes through the same permission checks you do, so it sees what you see and nothing else. Deleting, archiving, resetting, bulk edits, sharing and AI generation stay out. File downloads, who voted in a poll and who has read a notice are deliberately left out.

### Changed

- **Sheets: copying keeps the formula** — a copied block used to paste the numbers it happened to be showing. It now pastes what you copied — formulas, with their references moved by however far the block moved, and the bold, fills and number formats that went with them. Cut still moves a formula unchanged, and moving one to another tab now spells out the sheet it came from so it keeps meaning what it meant.
- **Sheets: copy and paste between tabs** — clicking a tab moved the keyboard off the grid and nothing gave it back, so pasting onto another sheet could not work and Ctrl+C stopped responding after any toolbar click. The grid keeps the keyboard now.
- **Sheets: typing into a cell you have scrolled past** — a selected cell that had scrolled out of view opened an edit with no box to type in, and swallowed everything after. It scrolls back into view and takes the text. Arrow keys can no longer walk the cursor off the edge of the sheet either, and pasting more than fits now says how much did not, rather than dropping it silently.

### Fixed

- **Sheets: a formula that reads another formula** — `=IF(B9<0,0,B9)`, `=SUM(A2:A9)` and anything else pointing at a cell that is itself a formula could come back `#ERROR!`, and whether it did depended on where you had scrolled. It doesn't any more. `=INDEX(Data!A2:A9, …)` also read from the wrong sheet, and now reads from the one it names.
- **A dashboard tile that joins text together, or reads a part out of a date, draws again** — a widget whose query used `concat` or `extract` was refused by the database instead of answered. That is what broke *Who is carrying what* on the *Project health* and *Team activity* dashboards, and any tile of your own written the same way. Both draw again, and nothing needs re-saving.

## [0.67.0] - 2026-09-09

### Added

- **The phone app takes the picture, and reads with no signal** — every image upload (profile picture, community icon and banner, document images, notice screenshots) now offers the camera beside the photo library. And silence from the server is no longer read as a rejection: instead of the sign-in screen you get the tasks, documents, notices and calendars this device had already loaded, for up to a day, behind a bar saying when it last updated. Reading only.
- **Reactions can be turned off per notice** — a switch beside the comments one, on by default; turning it off keeps the reactions already there.
- **The bell can be turned down** — every notification setting used to govern email and mobile only, so the bell filled at the same rate whatever you switched off. It is now a channel of its own, with a switch per category, and a category that names you keeps it whatever else you do.
- **Quiet hours** — hold email and mobile overnight, in your timezone. The bell still collects, and when the window ends one message says what happened rather than replaying a night of them.
- **Notifications have a page** — **/notifications** holds everything that has happened, read and unread, grouped by day, filterable by community and by what names you, with mark-unread and dismiss on every row. The bell's popover is now what is still unread, all of it.
- **Every community has a dial** — set one to say everything, only what names you, or nothing, without touching any other. A per-category grid for a single community sits behind it for anyone who wants one.

### Changed
- **The dashboards that ship with Initiative answer a check-in** — *Project health* now says how far along each project is rather than only how many tasks it holds, what is past its date, what got finished lately, and deals every open task into a column per person with each card led by its project. *Team activity* gains the same board and what is still open; *Task flow* stops showing the same figure twice and shows what has been waiting longest; *Delivery timeline* and *Event planner* gain what is late and what is coming up. Anyone who installed one keeps what they have until they choose to take the new version.

- **The bell shows how many again** — a count on the bell, and a dot everywhere else. The number is about one list and answers "how much is waiting"; repeated down the community, initiative and tool it would be arithmetic, and there the only question is where to go.
- **A dashboard widget is pointed at data by clicking, or by SQL** — eight kinds of data source collapse into one **Build** step: pick what to read, which columns and what to group by, and the dashboard writes the query, with the widget that draws it a separate choice. A **SQL** tab beside it takes the questions clicking cannot describe, with datasets offered as you type and the statement checked as you pause — one-way for that widget. Stored widgets were converted; anything the conversion could not express is named in the upgrade log.
- **A dashboard counts work by the person doing it again** — grouping by assignee was the one thing the old widgets could do that a query could not, so *Work by person* had become a grouping by project. A query reads this community's members now — their names and what is assigned to them — and a community that shows handles groups by handle. It sees what a member list already shows you: this community's people, nobody else's.
- **A chart can be pointed at an app's data** — an installed app's reads could only be drawn by that app's own widget, because its rows were its own shape and nothing else knew how to read them. A widget bound to an app now takes a query over those rows, so the community's own charts, tables and totals can group and filter what an app returns. What the app hands back is what its listing already declares, so a query naming something it does not send is refused as you write it — and twenty people looking at the same tile are still one call to the app.
- **A dashboard can show everyone the same figure** — a tile normally shows each person what they can already see, which is right until the number has to be common ground. Name a project under *Published figures* and every tile reads it the same way for everyone who can open the dashboard, with a line on the dashboard saying so. You can only publish what you can open yourself; whoever owns it sees the share and can take it back at any time; and if you lose access, leave or are suspended, it stops showing rather than carrying on without you.
- **The SQL tab offers what a dataset can be read alongside** — typing in a statement about tasks now suggests *assignee*, *status* and *project* beside its own columns, and a name written after one of them completes against what it reaches, so *assignee.display_name* can be found without knowing it was there.
- **A dashboard tile can be narrowed by clicking** — the Build step has filters beside its columns now: pick a field, how to compare it and what to compare it against, bracket a few as *any of these*, and choose **Me** wherever a person goes. Dates are asked as distances, so a tile set to *the next 30 days* still means that next month.
- **A dashboard tile can be about whoever is reading it** — a query can say **me**, and it means the person looking at the tile. One widget, placed once, then answers per person: my open tasks, the queue items waiting on me, what I created this week. Each reader sees what they would see anyway, and the widget itself holds nobody's name.
- **A dashboard can ask about everything, and about what things are attached to** — documents, queues and their items, calendars, notices and dashboards themselves can all be counted, filtered and charted now, where only tasks, projects, counters and events could be. And a query reaches what its subject is attached to without anybody describing the link: tasks by the person assigned, by their status, by their project — pick the related column and the dashboard works out the rest. Dashboards stay read-only; this is only what they can be asked.
- **What you can reach is your role, and viewing is enough to reply** — a share now reaches somebody only if their initiative role lets them use that tool, and says so instead of quietly doing nothing; and anyone a project, document, notice, queue, counter group or calendar is shared with as a viewer can comment on it and react, where both used to take edit access.
- **A community answers about a person in its own terms** — approving a member returns their handle, picture, standing and initiative places rather than their whole account record, and a community that shows handles now asks the database for people without their names. Nothing changes on screen.
- **Webhooks: polls in, drafts out, and what each change sits inside** — answering a poll now sends the notice update and never names the voter; a draft sends nothing until it is published; and every change names its surrounding items as `{type, id}` pairs. Additive — existing subscriptions need no change.
- **Comments arrive as one line per thread** — twenty comments on a task you are on used to be twenty notifications, twenty emails and twenty pushes. They now roll up into a single line naming who commented and how many, and interrupt once. Reading it starts a fresh one, so new activity is still news.
- **Mentions and ambient comment traffic are separate settings** — one switch used to govern both being named and somebody commenting on a task you happen to be assigned, so the only way to quieten the second was to lose the first.
- **Nothing is counted** — the bell, and every community on the rail, show a dot rather than a number. Opening the bell shows every unread item, which is what the number was standing in for.
- **Notifications mark read on click** — the dot moves as you click and comes back if the server refuses. Times are relative now, with the full date on hover.
- **Bursts of change stop stuttering** — a batch is worked out once rather than per item: a third of a second of unresponsive page becomes under a millisecond.

### Fixed
- **Dashboard tiles stop blinking empty** — a tile briefly showed nothing while the dashboard around it reloaded, then showed its figures again.
- **A funnel's bars stay inside their tile** — a funnel measured every stage against the first one rather than the largest, so a set of stages that does not narrow drew the bigger ones past the edge of the panel. Dashboard tiles also clip what they hold, so no visual can spill across the one beside it.
- **A dashboard tile nobody has pointed anywhere stops reporting a failure** — a widget placed but not yet given anything to show asked the server for a statement it does not have, and drew that refusal as data it could not load.
- **An empty heatmap says it is empty** — a daily-activity tile with nothing to show yet reported that it had no date column to place values on, sending its author to fix a query that was never wrong.

- **The unread dot reaches the initiative and the tool** — it lit the community and stopped there, because almost nothing recorded where it happened: a mention, a reply, a comment or an assignment named its community and nothing inside it. They carry the initiative and the tool now, so the dot runs all the way down the sidebar and finding what happened is following a trail. On the rail it also moves onto the community's picture, where a presence dot sits, rather than hanging off the corner of the square behind it.
- **Notifications reach people again** — an unreleased change had put a read rule on the notification table that also governed writing it, and a notification is written for somebody other than the person who caused it. Inviting someone to an event, changing or cancelling one, replying, commenting and assigning all failed with a permission error instead. Nothing was lost; nothing was sent either.
- **Events, notices and reactions carry where they happened too** — the unread dot reached the initiative and the tool for mentions, replies, comments and assignments, but an event reminder, a notice going up or a reaction still named only its community, so an inbox holding those lit the community and nothing under it. All three record their place now.
- **Everything a community shares now updates live** — documents, queues, counters, calendars, dashboards, tags, comments and notices all sat there until you reloaded, and so did a community you had been removed from or an initiative you had just joined. Updates now come from the record of what changed rather than the screen that made it, so imports, background jobs and scheduled notices are covered too; they reach every window on a multi-process server; a heartbeat every thirty seconds catches a connection that died without saying so; and reconnecting or returning to a background tab catches up. The bell no longer polls.
- **What you were typing is no longer taken back** — a fresh copy arriving from the server used to overwrite the page you were working in. In a document that meant autosave skipped your writing and leaving threw it away without warning; in a settings form it meant a half-written description, an SMTP password, a storage key or an identity provider's details reverting. Both are now filled in once and left alone.
- **Direct messages set up on a deployed server, and their notification switches save** — the encryption worker is WebAssembly and was served without a policy leaving room to compile it, so *My Messages* failed on every install while working in development; it now gets the same narrow policy the widget sandbox has. Separately, the direct-message and reaction switches were written to a hand-listed set of preferences they had never been added to, so they went back on at every reload.
- **A read-only look at a community holds no writes** — approved read access and read-only membership carried the same shared-record permissions a full member's does. Nothing ever wrote by that route.
- **Signing out clears whiteboards held on the device** — the local copy of a scene stayed behind for the next person on a shared computer.
- **Editing a comment no longer reports an error it had not had** — the edit went through and came back a server error anyway; the reply now carries the comment back whole.
- **A link naming the wrong initiative redirects instead of crashing** — building the corrected address failed and the page fell over with *Something went wrong*.
- **Every picker opens on something** — templates, document attachments, queue links, `#` references, `[[ ]]` links and mentions all showed an empty menu until you typed; they now open on what was most recently worked on.

## [0.66.1] - 2026-09-07

### Fixed

- **Upgrading no longer stops when Initiative connects to its database as the database's own owner.** An install from before Initiative had its own least-privilege login names one PostgreSQL role for everything, and 0.66 asks for a fourth connection made as the database owner — which on those installs is that same role. Startup then tried to give it the shape a purpose-made provisioning login gets, PostgreSQL refused (`permission denied to alter role`), and the app never came up. Startup now leaves a role that is already a superuser with exactly the privileges it had, and goes on to everything else. The banner asking you to move that connection to `app_provisioner` is unchanged, and it is still worth doing.

- **The direct-message privacy setting that was never added.** A deployment that ran 0.65 got the direct-message settings table without the column behind the read-receipts switch, and 0.66 had no way to notice: opening messaging settings failed with `column user_dm_settings.send_receipts does not exist`. The column is now added wherever it is missing.

- **Purging a task somebody was assigned to.** Emptying one from the trash failed outright, and the hourly clean-up that removes trash past its retention came back to the same task every hour and failed there too. Assignments are now removed with the task, as every other part of it already was.

- **Handing a community's content to another admin.** Both *Claim unowned content* and *Transfer ownership*, on the community's member screens, failed with a permission error instead of moving anything: the check that the recipient is an admin was reading the account list through a connection that a community's screens deliberately cannot read it through. It now reads the same member roster the rest of those screens do.

- **The whole app no longer scrolls out of the window on a long comment thread.** On a task with enough comments, or a file document with them, focusing the comment box or scrolling over the sidebar moved the entire app — sidebar, header and all — up out of view, leaving a blank band underneath that nothing could scroll back from. The hidden "Delete" label on each comment was being measured against the window instead of the page, and enough of them below the fold made the window itself scrollable.

## [0.66.0] - 2026-09-07

### Added

- **Posts: a bulletin board for an initiative.** A new tool, beside Documents and Calendars: a place an initiative says things out loud — a change of plan, a date, a welcome. Posts are written in the full editor, so a notice can carry pictures and live smart chips that go on showing a task's current column long after it was written, and each one is shared, tagged, commented on and reacted to like anything else here — or has its own comments turned off. The board reads newest first and loads five notices at a time as you scroll rather than paging, keeping only the ones near your screen loaded, so an hour of scrolling costs the same as a minute of it. Every notice is signed: whoever wrote it, above the headline, the way a comment is.
  - **Pins, with an end date.** A manager pins the notices that matter to the top, and can put a date on the pin — so a notice about Sunday stops shouting on Monday and drops back into the feed by its own age without anybody having to remember it. Pinning is still one click; the end date is the optional second one, next to the sentence that describes it.
  - **Write it now, post it later.** Set a time and the notice stays a draft — nobody sees it, it is in no board, count or search result, and nobody is told — until the hour comes and it goes up on its own. Until then it sits on the board of whoever can edit it, marked as not yet posted, with one button to put it up straight away.
  - **The people it is for are told.** When a notice goes up, the people it was shared with hear about it: in the bell, and by email and push if they want them, with a new *Posts* switch under notification settings for both. Shared with three people, it interrupts three people — posting to a corner of a large initiative does not ring everyone's bell.
  - **A board knows what you have read.** A notice is marked read once it has been on your screen for a moment — long enough to be reading it rather than scrolling past — so nothing asks you to tick anything off. Each one says how many people have read it, and opens a list of who has and who it is still waiting on: the people it was shared with, not everyone in the initiative, because a notice sent to five is not ninety-five people ignoring it. There is a button to put one back to unread, and a filter to show only what is left.
  - **Ask a question on a board.** A notice can carry a poll: a question, up to ten choices, and one click to answer. Pick one or pick several; change your mind, or take your answer back, for as long as it is open. You can set a time it closes, keep the numbers hidden until somebody has answered so the early votes do not sway the later ones, or make it anonymous — which shows the totals and never the names. Otherwise a tap opens who chose what, and who has not answered yet, the author among them, because writing a question does not stop you answering it. Once people have answered the choices are fixed and anonymity cannot be switched off; everything else about the poll is still yours to reword.
  - **Jump a board to a date.** A rail down the side marks every month that has notices, longer where a month was busy, and a drag scrubs through them with the month named under your finger. On a phone the notices get the whole width: the rail stays out of the way until the board is moving, when a thumb appears at the edge saying how far down you are — grab it and the months come out to meet you, drop it and they go again. Picking one glides to it when it is already loaded and re-anchors the board there when it is not, so reaching last spring is one request rather than scrolling through everything since. A board you have jumped to reads as a chronology — pins step aside, because a pin says what matters now rather than what mattered then — and one line says where you are with a way back to the latest. The rail is built to be reused: the next tool that wants a timeline gets the same control.

- **Direct messages, end-to-end encrypted.** My Messages, in the sidebar, marked *alpha* because it is new and still moving: the conversations you have open, and a composer. Messages are encrypted on your device and decrypted on theirs, so the server carries bytes it has no key to — there is nothing to search, nothing to moderate and nothing to hand over. A conversation opens once a message request is accepted, so nobody arrives in your messages uninvited. Notifications name who wrote and count how many, never what they said, and a flurry of messages is one notification rather than twenty.
  - **A conversation lives on your devices, not on a server.** A message is delivered and then deleted, which means each device keeps its own copy and a device that has never been in a conversation starts empty. Signing out takes this device's messages with it, which is the right answer on a shared computer — and the wrong one if you wanted them back, so keep the conversations you care about open on a device you stay signed in to.
  - **Your messages follow you to a new device.** Sign in somewhere new and it starts with nothing, because there is no copy on the server for it to catch up from — so it asks your other devices, and one of them offers to send its history over. Both screens show the same six pictures — a dog, a rocket, a bell — so checking that a device is the one in front of you is a glance rather than a line of base64 nobody reads to the end of, and approving a device is remembered: you are asked about the device, not about every conversation. The device that is waiting says so, and stops saying so after a day — long past the point where somebody was going to go and approve it, and without giving up on the answer, which still lands whenever it comes. Signing in as somebody is enough to receive their new messages and deliberately not enough to receive their old ones.
  - **A thread looks like a conversation.** Each person's picture sits beside their messages with the clock time under it, once per run rather than once per line — and a run ends when the other person speaks *or* when five quiet minutes pass, so two messages an hour apart never share a time. Days are headed where they change, the two you are most likely reading by name rather than by date. The composer grows as you type: Enter sends, Shift+Enter starts a new line, and the message keeps the shape it was written in.
  - **Do something about a message, not just read it.** Hovering one on a wider screen floats a small bar over it — react, reply, and on your own messages edit and remove; on a phone a button beside the message summons the same bar. A reply quotes the line it answers, an edit says *(edited)* and keeps its place, and a removal leaves *Message removed* rather than a hole, so an exchange that referred to it still reads. All of it travels the way a message does: encrypted end to end, applied on your device first, and honoured by theirs — a removal takes the message off their copy because their client does it, which is as far as anything can reach once words are on somebody else's device. None of the four rings their bell; only a message does.
  - **Messages take markdown.** The basics — bold, italic, code and code blocks, lists, quotes, headings, links — the same ones a comment takes. Two things are deliberately left out. A picture is never fetched: it becomes a link with its name on it, because an image loading on arrival would tell the sender where you are and when you opened it, from inside the one conversation whose point is that nobody learns either. And a mention does nothing here, because it is read against a community's roster and a direct message belongs to no community.
  - **Delivered and read receipts.** A tick under your own message once a device of theirs holds it, and two once somebody has looked. It is the other side's client that reports, in an ordinary encrypted message the server cannot read — so the receipt is as private as the thing it is about, and it rings nobody's bell. Under Privacy there is one switch to stop reporting: turn it off and people see neither, which looks exactly like somebody who has not opened the app. You still see theirs.
  - **Requests, either way round, where you were sent to answer them.** Anything waiting on an answer sits above the conversations — asks to message *and* asks to connect, since both are the same question to the person reading them and both are answered here. Somebody asking you carries *Accept* and *Decline* on the row; anybody you asked carries *Cancel*, because an ask left off the page looks like one that never happened. The row says which of the two was asked for, and the mark in the sidebar counts the ones only you can move.
  - **The conversations are cut into sections.** Unread first, then favorites, connections, and everyone else you can reach — each one folds away, and stays folded next time. Anybody with something waiting is read at the top whatever else they are to you, because somebody has spoken and nothing further down is asking for anything. Somebody starred who is also a connection is listed once, under Favorites: starring is a choice you made about that person, and being connected is only how the two of you are linked. Set to Private there is nothing to list at all, and the page says which of your own settings emptied it and offers the two ways out.
  - **Find somebody the list cannot offer.** A field above the conversations narrows them to a handle as you type — nothing is fetched for it and nobody new appears, it only puts what is already there within reach. Beside it, a plus: the people you starred first — including anyone you share no community with, whom no roster will ever hold — then everybody you do share a community with, grouped by community and each headed with how many there are, and a box that also takes a whole handle, number included, which is the one way to reach an account no list of yours will ever show. A big community shows the first twenty and grows by *Show more* rather than paging, so the person you had just spotted stays where they were. Somebody who takes no messages is shown like anybody else and simply offers nothing to click.
  - **My Messages drills into the sidebar.** Opening it puts the conversations in the column the navigation was in, with an arrow in the header to climb back out — so the page beside it is only ever the thread, and a phone gets the whole width for it. With no conversation open the page shows that same list, which is what a phone lands on: the sidebar is a sheet there and shuts as soon as you pick anything. Every row addresses its person in the URL, so a browser's own back button, a middle click and a shared link all work.
  - **A mark when something is waiting.** A red dot beside My Messages in the sidebar for a message you have not read, or somebody asking to reach you — on the logo above the community rail too, which is the only thing pointing home from inside a community, and as a count on the bottom bar, where My Messages now has a place of its own: in the pill on a phone, and beside the create button on a wider screen. Unread is per device, because a conversation is: your messages live on the device that collected them, so what you have read is a fact about that device and nothing else could answer it.

- **Say who can message you.** A Privacy tab under your profile settings, with one question at the top: who can ask to message you, outside your connections. *Private* means no one, *Anyone* means anybody here may ask, and *My communities* means people you share a community with — with a switch per community under it, all counting by default, so you can be reachable in one and not another. Asking is always a request and it is always yours to accept; nobody arrives in your messages because they found you. The shipped default is Private, and Settings › Community picks what new accounts start on — read once, when the account is made, so changing it opens no account that already exists and closes none either.

- **Connections.** A connection is mutual, and it is how two people stay in touch after the thing that introduced them ends — you can keep messaging even once you no longer share a community. You make one by typing somebody's full handle, number included, so a private account is reached by someone who was given it rather than by being picked off a list. Requests wait in one place, either direction, and a connection you accept opens the channel with it: having agreed once, you are not asked again.

- **Ignore an account.** They stop reaching you: no notification when they mention, reply to or react to you, and nothing they send arrives — messages, message requests, connection requests. You will still see each other's activity in communities you share and can use every tool normally, because ignoring is about contact rather than about work. Nothing is deleted, so if you stop ignoring them everything is exactly where it was.

- **One menu for everything you can do about a person.** On their profile, on a community's roster, and on every row of the conversation list: go to them, copy their handle, star them, message them or ask to, connect or unconnect, and ignore — with removing a connection confirming first. Each place leaves out only what it already offers beside it, so starring, which used to exist only as a star beside a name, is on a profile too, and ignoring no longer means knowing an account's exact handle and opening Settings. A profile leads with the two actions worth a click rather than a click and a read — *Message* where the channel is already open, *Ask to message* where it is not, with *Connect* beside them, and a request already sent stays on screen as a spent button rather than vanishing. On a row the menu waits out of sight until the cursor is over it, and is simply there on a touch screen, which has no hovering to do.

- **A community lists its members.** The member count on a community's banner now leads somewhere: a page of everyone who is here, searchable and paged, with the same *Message*, *Ask to message* and *Connect* buttons a person gets anywhere else. Somebody who takes no messages is listed like anybody else and simply offers nothing to click — they are here, and they are not reachable, and the page says both.

- **A board widget for dashboards.** Tasks dealt into columns, and you choose what a column stands for: a status, the people on the work, priority, project, tag — or one of your initiative's own properties, so a board can be columned by a field we have never heard of. A value that exists and has nothing in it still gets its column, because a state nobody is in is usually the one worth seeing. Cards carry who is on the work, the due date and the checklist; anything past its date reads red and its column says how many. Read-only like every widget on a dashboard — a card is a card, not a handle, and moving work between states is still a project view's job.

### Changed

- **Pages draw their outline while they load.** A page that is still fetching now shows the shape of what is coming — a title where the title will be, rows where the rows will be — instead of a spinner or a line of *Loading…* off to one side. The initiative page, the community home, every tool's list and detail page, the tables under My Tasks, My Tools and a tag, and the settings panes all have one, and moving between an initiative's tool tabs or a settings page's tabs only redraws the part that is changing. A page whose data was held back until it arrived now opens at once and fills in, so a cold load is never a blank window.
- **My Projects and My Documents are one page: My Tools.** Two pages that were the same table for one tool each are now one. Pick a tool at the top and see everything of that kind that reaches you, across every community you're in, rather than one community at a time. A tool you have nothing of anywhere gets no tab, so the page never opens onto an empty table. A toggle switches the whole view between everything that reaches you and only what you made, and the tool, the search, the order, the page and the communities you're filtering to all ride in the address — so any view of it is a link you can send.
  - **Tasks I Created is gone.** My Tasks already answers the question it answered, and answers it better: the toggle at the top of My Tools has the same reach across every community you're in, and a task you made is a task you can find by its project. The page, its sidebar entry and its place in the command palette are all removed.
  - **The command palette lists pages, not tools.** *All Projects* and *All Documents* were two tools singled out of the eight, sending you to the community home with that tool picked — which is what the community home opens on anyway. Type a project or a document's name and the palette still finds the thing itself.

- **Install with one file and nothing to run by hand.** Initiative now creates its own three database roles at startup and installs the search index's match operator with them, using a new `DATABASE_URL_BOOTSTRAP` connection for the database owner. The example compose file no longer carries a block of SQL for the database to run when its volume is first created, and search no longer waits for somebody to pipe a script between two containers — until now, an install from Docker Hub read more of its index on every search until an operator noticed the startup warning and ran it. Because the bootstrap runs on every start rather than once per volume, changing a role's password in its URL and restarting is enough to rotate it. Existing installs need no action: the roles they already have are re-asserted, and the search operator they were told about gets installed on the next start. You can also remove `DATABASE_URL_BOOTSTRAP` once the stack is up — Initiative then checks those prerequisites instead of applying them and names anything missing — and a deployment whose database is provisioned elsewhere can leave it unset and apply `python -m app.db.bootstrap --print-sql` itself.

- **The age question is asked where it stops you.** Messaging is for people aged 13 and over, and an account that has not answered that had one place to answer it, which was not where anybody hit the wall. The question is now on the Privacy tab — which is where somebody goes to change who may reach them, and where every control it gates already lives — and it is the whole of My Messages until it is answered, rather than a composer and a list that could only ever be empty. Answering refreshes what it opened rather than needing a reload.

- **The account row at the foot of the sidebar is one line.** The status used to sit under your name in a bubble of its own with a presence dot beside it, and the pair cost the sidebar a whole extra row. The picture carries the dot now, the way it does everywhere else you appear, and the status reads as a line under your name. The menu that row opens leads with the banner and picture you wear and the handle you go by, with the thought bubble over the banner — still what you click to change it. Under that, *Set status* and how you appear, named by the state you are in. The theme moved in as well, and *Admin Dashboard* and *Platform Settings* now sit in a section of their own. *My Stats* and *Community Settings* left the menu, both already reachable from the sidebar itself.

- **The comment switch says what it does, and sits where you'd look for it.** Turning comments off on a project, document, board, queue, calendar or dashboard used to mean opening *Advanced* and answering yes to *Disable comments*. It is now *Comments* on the *Details* tab, on to begin with, and switching it off switches comments off. Nothing already posted is deleted either way — it is all there again the moment comments come back.

- **User Settings is My Settings.** It sits among *My Profile* and *My Tasks*, and it was the only one of them naming you in the third person. Renamed in the account menu, in the command centre and on the page itself.

- **A reaction shows its number only when there is one worth showing.** One person behind an emoji is what the emoji already says, so the chip is just the emoji until a second person joins it. The count is still spoken to a screen reader either way.

### Removed

- **My Contacts has been retired; My Messages does all of it.** The page was a directory of everyone you shared a community with, and the only thing anybody ever did from a row was reach for one of them — so the reaching moved to where the conversations are and the page stopped earning its place in the sidebar. Everything it held has a home: the people you can talk to are the conversation list, grouped and searchable; requests either way round sit above them; starring, ignoring, connecting and the rest are on the menu on every row; and the **+** finds anybody you have not messaged yet — your starred people first, then each of your communities, then a whole handle for somebody in none of them, each row carrying the same star and the same menu a contacts row did. A community's own roster still lives on its member count, where it is about that community rather than about you. Old links to `/contacts` land on My Messages rather than on nothing.

### Fixed

- **No white flash on reload in dark mode.** The page now paints in the theme you chose from its very first frame, before the app has loaded, instead of showing a white window until the interface arrived.
- **Turning a tool on now says who can actually see it.** Enabling Posts, Queues, Counters, Calendars or Dashboards for an initiative was only half of what it looked like: the initiative offered the tool, but each role still needed its own permission to see it — so the manager who flipped the switch saw the tool appear and every ordinary member saw nothing, with neither screen mentioning the other. The switch now asks the question at the moment it matters: turn a tool on and choose whether it is for everyone or for managers for now, and the row underneath names the roles that can see it, warns when only managers can, and grants it to everyone in one click. Turning a tool off says what it hides — everything in it, from everyone — and that nothing is deleted. The Roles screen carries the other half of the pairing: a tool the initiative has turned off says so, above permissions that grant nothing until it is back on.

- **Roles remember the tools that shipped after they were made.** A role created before a tool existed stored no permission row for it, so a Project Manager role from before Posts carried 12 permissions where a new one carries 14. Nothing was mis-authorized — an absent row read as its default — but the stored role had drifted from the role the code describes. Every role now carries a row for every tool, at the value it would get today, and permissions somebody had deliberately turned off stay off.

- **The emoji picker fits the screen the keyboard left you.** Picking an emoji — for a status, a project icon or a reaction — opens a search field, which opens the phone's keyboard, which takes half the screen; the picker asked for its full height anyway and the top of it, search field included, ended up above the top edge. It is now never taller than the room it actually has: the grid of emoji gives way and scrolls, and the search field and the label naming what you are hovering stay where they are.

- **Dialogs fit the phone they open on.** Create dialogs were cut off down the right-hand side on a narrow screen — the sharing card, and with it the access level, sat off the edge. Two causes: the dialog's grid would not let its contents shrink to it, and a dialog asking for its own width dropped the screen-width cap at every size rather than only on a wide one. Both are fixed for every dialog in the app, not just the ones anybody noticed.

- **A search tab that matched nothing says so.** In ⌘K, switching between Tools, Members, Comments and Tags left the tab before it on screen when the new one had no answer — so a community with nobody matching showed the comments you had just been reading. Each tab now shows only what it found, and says "No results found." when that is nothing — or that search is not answering, if the request never landed, rather than reporting a failure as an empty community.

- **Leaving a task you have not edited no longer asks whether you want to lose your changes.** The guard that protects half-written work armed the browser's own reload warning whether or not anything had been typed.

- **Everyone in a community hears that it was listed.** The notice that a community joined the directory — which is what asks its members their age — only reached people whose tab happened to be held by the same server process that made the change. On a deployment running more than one, everybody else waited until they next navigated.

- **A list's filter box says what it searches.** It was labelled "Filter by name" on projects, queues, counters and dashboards, and it has always searched the description too — the same index the search page reads. It now says "Name or description", and the API says so as well, having described itself as a name match since it stopped being one.

- **A profile's communities say how many people are in them.** Each card counted nobody, because the profile's own read never asked for the number — a community somebody belongs to has at least one member, so "0 members" was never true.

## [0.65.0] - 2026-09-02

### Added

- **Search that finds everything in a community, and reads inside it.** ⌘K and a results page of its own reach projects, tasks, documents, queues, counters, calendars, dashboards, tags, comments and people — matching names, descriptions, and the words inside a document, whiteboard or spreadsheet. Results are ranked, show the line that matched, and answer before you finish a word; a misspelling is offered the closest names rather than an empty page. Archived work is kept back unless you switch it on.

- **Point at other work from anywhere you write.** `@` names a person, `#` names anything that exists, and `[[ ]]` names a tool — and offers to make one that doesn't exist yet, in place, without leaving the sentence. All three work in every comment and in text documents. References keep up: rename a task and every sentence mentioning it says the new name, with nobody editing anything. A document's backlinks count them all, not just `[[ ]]` links.

- **People have profiles.** A page of your own with your picture, your handle and what you're up to — a status emoji and line, both optional, set by clicking the bubble rather than filling in a form.
  - Settings › Profile picks the look around it: a banner across the top, a frame on your picture, and a rail of trophies under it, in the same shape a community's front page has. Where that page holds a table of projects, a profile holds cards for the communities the person is in, of the ones that opted into the directory.
  - It travels with you — the frame and the status show in the sidebar and beside every comment you write — and the settings tab previews the card a stranger sees as you build it.

- **Announcements.** The "a new version is running" prompt grew into a way to tell people anything: a notice with a title and as many sections as it needs, each with its own heading, markdown and screenshot.
  - Mark a section as starting a new page and the notice becomes a wizard the reader steps through. Pictures open full size on a click.
  - Each notice is shown once and remembered per person — or, for a breaking change nobody can afford to miss, ask for however many acknowledgements it takes before it stops coming back.
  - Choose who sees it: a minimum platform role, optionally "only people who administer a community", and either the accounts that existed when it was published (a change you lived through) or the ones made since (a tip for somebody just arriving). Schedule it, give it an end date, or keep it a draft.
  - Give it a page pattern instead and it waits there, so a notice can explain a screen on the screen it is about.
  - Operators and owners write them under Settings › Admin › Announcements, with a preview of exactly what a reader gets. Everyone can re-read past notices from the info icon in the sidebar footer, where read and unread are marked and unread can be filtered to on its own.
  - A release can also ship a notice in the app's own source, naming the version it matters to so a fresh install isn't told about every change since the one before it. This release ships one, telling community admins where their sidebar's initiatives went.

- **Communities ask their members' age — and don't keep the answer.** Joining a community anyone can find asks your date of birth once. It is used to check you are old enough and then discarded: your account records that you answered, never the date. Only the parts of Initiative open to people outside your own communities ask; private ones never do. An answer of "not old enough yet" is kept too, so the question is asked once rather than until it comes out right — support and above can reset it for the usual cause, a mistyped year. Platform owners can turn the question off entirely under Settings › Admin › Community.

- **Say how you're around, or don't.** A dot under your picture in the sidebar opens the four states: online, idle, busy, or offline. Offline means offline — nobody sees you as here, whatever you have open. Idle sets itself once nothing has been touched for a while, and you can also pick it outright to say you have stepped away. The same dot on your profile card in Settings › Profile opens the same menu.

- **My Contacts.** Everyone you share a community with, on one page: favorites you picked at the top, then each of your communities in the order you dragged them into the rail, as sections you can collapse.
  - It reads as one table — the same columns (person, name, the communities you have in common) run down every section, so somebody in several of your communities lines up with themselves. Hover the small community icons on a row for the full list of what you share.
  - Each section pages on its own, twenty at a time, without moving the ones around it.
  - Star anyone, including people you share no community with, to keep them at the top. Starring is private and tells them nothing.
  - One search box covers the whole page, and says while it works that a search visits each community in turn.

- **Smart chips: a chip that keeps itself current.** Type `/` in a document, or pick **Smart chip** from the toolbar's insert menu, and choose a task's status, assignee, due date or priority, a counter's value, or an event's date. The chip carries the reading itself — `In progress`, `42 / 100`, `12 Sep` — so it sits in a sentence without repeating what the sentence already says; hover it for what the thing is called now and what kind of thing it is, and click to open it. Move a task to Done and it turns green in every document that mentions it.

- **Comments grew up.** React with an emoji (the author hears about it in a digest, not one ping per thumbs-up), turn comments off per tool under Settings › Advanced, and read them through the MCP server as well as write them.

- **Your account keeps up with itself.** A tab used to read your account once, when it opened, and never again — so being added to a community by an admin or a group sign-in sync, or a community listing itself while you were already in it, went unnoticed until you reloaded. Those now reach an open tab as they happen. Nothing about the change travels: the tab is told only that something moved and reads your account back the normal way, so what it can see is exactly what it could always ask for. Deployments running more than one server process get this too, over the database they already have — no extra service to install.

- **Shift-click picks a run of cards.** Selecting projects, documents, queues, counter groups or dashboards no longer means one click per card: click the first, hold shift and click the last, and everything between them comes with it. Shift-clicking away from a card you just unticked clears that run the same way.

- **Pickers open on what you were just working on.** Choosing what a smart chip is about starts from the work in this initiative you edited most recently, so the common case is picking from a list rather than guessing at a search term. Typing still searches.

- **An initiative's status columns can be read in one request**, instead of asking project by project and stitching the answers together.

### Changed

- **Guilds are now communities.** The name was picked for gaming guilds, and people turned out to be running far more than that. Pages moved from `/g/…` to `/c/…`, and a new install's first community is called "Primary Community".

- **Exports and imports name people by handle.** An export used to write each person's email address as the key for assignees, event attendees and person-typed properties, and an import matched on it. Both use the handle now — `foobar#1234`, the identifier the rest of the app already uses, and the one that is the same in every community. Anything exported before this release will not match its people back on import; re-export and the new file will.

- **A community admin sees the initiatives they're in**, not every initiative in the community — in the sidebar and on the community's front page alike. An admin reads the front page the way anyone else does: the initiatives they joined, then the ones on offer. Their authority over the community is unchanged; it simply no longer decides what they navigate. They put an initiative in front of themselves by joining it from the front page (an admin walks straight in rather than asking, whatever the initiative's joining setting) or by taking the project manager role in Settings › Initiatives, which still lists every initiative in the community.

- **A list that spans initiatives shows what has been shared with you.** My Projects, My Calendars and the community front page's table each answered "everything you could reach", so a community admin got hundreds of rows from initiatives they had never been in. They now list what reaches the reader: shared with them, with a role they hold, or with everyone in an initiative they're in. The sidebar's tool lists and the per-initiative counts on the front page's cards follow the same rule. Opening a single initiative still answers with all of its work.

- **Notifications arrive when they happen.** The bell asked the server every thirty seconds, so a mention could sit unseen for half a minute while every open tab kept asking all day. It holds an open connection now, and marking one read updates your other tabs.

- **Every picker searches the way search does.** Mentions, wikilinks, queue links and template pickers each had their own lookup — substring matching, no ranking, and a fixed list of three kinds of thing. They all use the search index now, so every one of them ranks, matches as you type, and forgives a misspelling. So do the people pickers.

- **Promoting someone to community admin lifts the initiative roles they already hold.** A promotion used to leave every initiative membership on the role they joined with, so the app went on treating them as an ordinary member there — they were not told when somebody asked to join, and the waiting-requests count on the community front page read zero. Those rows now move to project manager with the promotion, and one left behind by an earlier promotion can be put right from the initiative's Members tab.

- **Project managers can invite community admins into an initiative.** The invite used to be refused, because an admin can only hold the project manager role there. It now simply gives them that role, so a manager can add an admin without first working out who is one — and the member picker offers them like anybody else.

- **User settings reorganised, and every tab is built from the same parts.** Profile and Decorations each held half the answer to "how do I look"; Profile is now the whole face and opens first, with sign-in details moved out of it. Nine tabs that had drifted into three kinds of heading and Save buttons in four places share one section component, and Notifications splits into the three things it was doing at once.

- **Search moved into the sidebar** and the results page names the community it's searching. Every tab stays open, so an empty one says so rather than being greyed out.

- **The task editor stops repeating itself.** Creating and editing a task now lay out the same named sections in the same order; the title is on screen once instead of three times; and the row of six buttons is two, with the rest behind a "…" menu.

- **A community's member list carries what the community manages.** Handle, name, community role, whether the membership comes from a group sign-in sync, standing, and when they joined. Their platform role and whether they have confirmed their address were in there too, and are not a community's business; both are gone from the list and from the member CSV.

- **Names and titles no longer accept `#` or `@`.** Both already mean something when you're writing.

- **Comment threads run the full width of the page**, on every kind of page, and each level of nesting draws its thread line in a different colour so you can see how deep a reply sits.

- **Every settings tab has an address of its own**, so you can link someone straight to a tool's sharing or advanced options.

- **One emoji picker everywhere**, searchable and in your language.

- **"Browse the marketplace" sits next to the create button** on the dashboards list rather than behind the overflow menu.

- **Toasts stay up only as long as they take to read**, worked out from the message rather than a fixed five seconds.

### Fixed

- **Open tabs no longer flicker when you switch community**, and document text no longer shows through the editor's toolbars.

- **A task description with a code block no longer stretches its board card** out of the column — code fences, tables, images and long strings stay inside it.

- **The community calendar shows its calendars** and offers to add one, instead of opening straight onto a grid of events.

- **A picker that finds nothing says so.** `#` and the smart-chip picker reach the work in the document's own initiative, so a community full of matching tasks can still answer nothing — and both used to render that as an unchanged caret and an empty box, which reads as a broken feature rather than as an answer. They now say that nothing matched, and that the initiative is the limit.

- **Renaming a spreadsheet sheet keeps what you type.** Every keystroke used to re-select the whole name and replace it.

- **The Repeat field no longer tells you twice** that a task doesn't repeat.

## [0.64.3] - 2026-08-30

### Changed

- **Link to documentation for help not the github page.**

## [0.64.2] - 2026-08-29

### Added

- **Connecting an app can now end with "waiting on an owner".** Some services hand an organization's install to the people who own it, so a request from anybody else becomes an approval sitting with one of them. The page you land on after connecting used to have no way to say that, and picked the closest thing it had. It now says it plainly: nothing failed, nothing is set up yet, and connecting again is worth doing once an owner approves it.

### Fixed

- **A model your provider offers is no longer rejected as "not found".** Testing a connection to an OpenAI-compatible service — OpenRouter and the like — checked the model against a list that had been cut to the first fifty entries, and those services offer hundreds. So anything past the cut came back as a model that does not exist, even though it does and the connection worked. The picker was reading the same shortened list, which is why only the handful it showed ever passed. Both now see the whole catalogue, and when a list really is too long to fetch in full, a model missing from it is no longer treated as proof of anything. The same fix reaches Anthropic connections, whose model list arrived one short page at a time.

- **Widgets that draw an app's data work again.** An app describes what each of its endpoints hands back — a name and a type for every value, and whether it holds several — and a widget is bound to those names before it ever runs. 

- **Publishing an app no longer drops the link between one of its dropdowns and the field it depends on.** An app can say where a parameter's values come from — one of its own reads, so a repository field offers that account's repositories rather than a text box. Where such a list depends on an answer already given, like the labels in a particular repository, the app also says which earlier field supplies it. That last part was being discarded when the app was published, so a dependent list could only ever be fetched unfiltered. It is now carried through and checked on publish: both sides have to name parameters that really exist, and a source cannot ask for the value it is filling in.

- **Dashboards that come with an app now appear in the marketplace.** An app can ship dashboards of its own — arrangements of its widgets, published with it, so an operator adds one file and the boards come too. 
- **Opening a link straight into another guild no longer loads the guild you were last in first.** A fresh tab starts on the guild it remembers and takes the one in the address a moment later, and in that moment the page was already asking for its data — so a link to another guild's board or marketplace briefly filled in from the wrong one before correcting itself. The page now waits for the address to win.

## [0.64.1] - 2026-08-29

### Fixed

- **Upgrading to 0.64.0 no longer fails on a database that has guild icons or profile pictures in it.** The two migrations that move those images into their own tables locked each table down before moving the rows, and the migration's own write was then rejected by the very policies it had just installed — so the upgrade rolled back, over and over, on any real deployment. A fresh install has no images to move, which is why it was never seen before release. Both migrations now carry the pictures across first and lock the table down after; nothing else about the result changes, and no manual step is needed — upgrade again and it goes through.

## [0.64.0] - 2026-08-29

### Added

- **The guild home's table searches and sorts the whole guild.** A search box sits above it, and the **Name**, **Initiative** and **Last updated** headers now order it — most recently updated first until you say otherwise. Both reach the guild's whole set for that tool rather than the rows already on screen, so a search never answers "nothing" while the match sits on page 4, and both ride in the address, so a searched and sorted table is a link you can send. Every circle behaves the same way: projects, documents, queues, counters, calendars and dashboards all take the same search and the same three orders.

- **Moderators can suspend an account.** Suspension is a freeze, not a removal: the person keeps every guild membership, every share, and everything they have written, and reaches no guild until it is lifted — at which point the account is exactly as they left it. They can still sign in to their own profile, where they are told it happened and why, so the app never simply stops working with no explanation. To everyone else they stop appearing in member lists, pickers and search for as long as it lasts, though work they already did still says they did it. Guilds are not told that one of their members was suspended.

- **Moderators can change a username.** For a handle that breaches the terms of use, the way a profile picture can already be taken down. The number beside it is unchanged, the person is told, and they cannot change it back themselves. All three moderator actions — picture, username, suspension — are recorded on the audit board, and none of them needs a break-glass grant, because none of them touches a guild's content.

- **There is an audit board.** Platform staff who can read audits — support and above — get a new Audit tab in the admin tools, listing what was done to accounts, by whom, and when, newest first, filterable by account. It starts with profile-picture takedowns, the one moderator action that exists today. Entries are kept after the accounts they name are deleted, so the record of what was done outlives the person it was done to; a deleted account shows as its ID rather than a name. Nothing can edit or remove an entry, including the software itself. Each entry is also written to the server log as one line of JSON, so an operator who ships their logs somewhere gets the audit trail with it.

- **Every guild has a banner.** It heads the guild's front page — the guild's own name and description across it — and runs along the top of its card in the community directory. A guild admin uploads one picture from Settings → Guild → Pictures and it is cropped to 4:1 and resized for you, so there is nothing to prepare and no second file to make. A guild without artwork wears a **banner fill** instead, which starts as the app's default blue and can be any colour; without a picture the banner is a short band rather than a full header. **Banner text** is black or white — whichever reads better on the fill, chosen for you when you pick one, and yours to switch when a picture calls for the other, and it now carries a shadow of the opposite tone so the words survive the patch of a photograph that goes the wrong way.

  The banner also carries the size of the guild — how many members it has, and how many have it open right now — and its layout is the guild's to set from the same panel. **Banner text position** is centered or left, where left lines the name up with the page's own content. **Banner fade** ends the banner at an edge, or carries it past that edge and dissolves it into the page so the tool circles and the table sit over its tail — soft or strong. A strong fade is the default, so a banner reads as the top of the page rather than a strip laid on it; a guild that wants the hard edge back sets the fade to none. The tool circles follow the banner's text position: centered under centered copy, and against the same edge when it is left. They are the top edge of the tray the table sits in rather than marks laid on the banner — each circle rises out of it and melts back into it — so a tool's name is always printed on that tray and stays readable over artwork of any brightness.

- **A guild-wide app connection can be granted at the vendor instead of typed.** A guild admin connects it once for everybody: the settings panel opens the vendor's install page rather than a form, and what comes back is written in by the app itself.
- **Initiatives can invite the whole guild in, and guild home says how.** Each initiative now declares how members may join it, under Settings → Details → Joining: invite only (the default, and what every existing initiative keeps) or open to anyone in the guild. Anything that isn't invite-only is listed on the guild home page — its name, colour, description, and how many people are in it — where a member can join an open one in a click and land straight in its work. A member who isn't in any initiative yet no longer meets an empty guild: guild home explains what initiatives are, lists what they can join, and says plainly when there's nothing on offer and an admin has to add them. "Browse initiatives" in the sidebar leads to the same list whenever the guild has one. Joining grants the built-in member role — view-only to start — and sharing still decides each item inside; nothing that was private becomes visible.

  That section is now the guild's whole initiative list, and the separate "My Initiatives" page is gone: the ones you're in come first — each card naming your role there and counting the work inside it, tool by tool, with the title leading in — then the ones you can join. The whole section folds away from its heading, per guild, and guild admins create initiatives from a button in it. Old links to the initiatives page (including the sidebar's "Add initiative") land on the guild home, and one that asked for the create dialog still opens it.

- **An initiative can accept requests to join instead of only invitations.** Alongside invite-only and open-to-anyone, an initiative can now ask people to knock: it is listed on the guild home like an open one, but joining waits on a project manager. A member asks with an optional note, the initiative's managers are notified and see the queue with who asked, what they said, and how many times that person has been turned down here before, and approving or declining notifies them back. Approving grants the same view-only member role every other join path grants — nothing that was private becomes visible, and declining changes nothing about what they can see. Being declined is not a ban: they may ask again, and only one request can be open at a time.
- **An open initiative can take in everyone who joins the guild.** A guild admin can mark an open initiative **auto-join**, and from then on anyone arriving in the guild — by invite, from the community directory, or through single sign-on — lands in it already a member, instead of an empty guild they have to find their way out of. It applies to arrivals from that point on and never reaches back over people already in the guild. Only an open initiative can carry it, so it hands out nothing a new member could not have joined themselves a moment later; guild admins are left out, since they already reach every initiative. A guild listed in the community directory is told when it has nowhere for arrivals to land, and can fix it from there.
- **Guilds can list themselves in a community directory, and be joined without an invite.** "Join a community" sits under the add-a-guild button in the left rail. It opens the directory: the search box and the category shelves take over the app's sidebar, and the page beside them is a card per guild with its icon, description, tags, and member count. Both the search and the shelf are in the address, so a filtered directory is a link. A guild admin lists theirs from Settings → Guild, picking at least one category and certifying the guild holds no adult or illegal content — the certification is asked at that moment and nowhere else, so a guild that keeps to itself is never put the question. A guild with room for only one member is never listed. Unlisted guilds are unchanged.

  Whether a server has a directory at all is the platform owner's decision, under Settings → Platform → Community, and it starts off. While it is off there is nothing to browse, nobody can join a guild without an invite, and the listing control is absent from guild settings. Turning it off later hides the directory rather than un-listing anyone: switch it back on and the same guilds are there.
- **An app service can be granted the app directory from Settings → Platform → App services.** Alongside "Act as members", the form now offers "Find other apps", which lets a service ask where another app installed in the same guild answers. An automation service needs both. It could previously only be conferred outside the app.
- **The community directory says who is in a guild right now.** A card carries the number of members with that guild open, beside the number of members it has in all. It is a live reading rather than a stored one, so it follows people arriving and leaving, and a guild nobody is in at that moment simply says how many members it has.

### Changed

- **An initiative's tool tabs read in the same order as the guild home.** Projects, documents, queues, counters, calendars, dashboards — one order everywhere, so the tab you reach for sits where the guild's tool circles taught you to look. An initiative that opens on no particular tool now opens on projects.

- **Guild icons are uploaded, not embedded.** An icon used to travel inside every reply that named a guild, which made a list of guilds far heavier than the list. It is now uploaded once, cropped square and resized for you, and fetched on its own — so it is cached between pages instead of resent with each one, and any picture works as a source rather than only a small square one. Existing icons carry over; one that isn't a square raster image under the new limit is dropped, and that guild shows its lettered avatar until a new one is uploaded.

- **Profile pictures are uploaded, not embedded.** A picture used to travel inside every reply that named a person — every task in a list, every comment, every calendar entry — so someone assigned to thirty tasks sent theirs thirty times in one response. It is now uploaded once, cropped square and resized for you, and fetched on its own, so it is cached across the whole app instead of resent with each list. Any picture works as a source rather than only a small square one. Existing pictures carry over; one that isn't a square raster image under the new limit is dropped, and that person shows their initials until a new one is uploaded. A picture linked from a single sign-on account is unaffected.

- **A profile picture can be taken down.** Moderators and above can remove someone's picture from the platform admin tools, for pictures that breach the terms of use. It removes the picture and tells the person; it never replaces it with anything, and no one can set a picture on someone else's behalf.

- **Everyone has a username, and it is what people see.** A username is a name you pick plus a number — `foobar#1234` — with the number added for you and shown quietly beside the name, so nobody has to accept `foobar7` because `foobar` was taken. Existing accounts get their first initial and last name — `Lee Janzen` becomes `ljanzen` — or a made-up one if there is no name to use; anyone whose username was assigned rather than chosen picks their own the next time they sign in. Where someone has not entered a full name, their username is shown instead of their email address.

- **A guild decides whether it shows real names.** New setting under Settings → Guild: on by default, and full names are shown where people have entered one; off, and members appear by username. A guild listed in the community directory always shows usernames, is never asked the question, and the setting is absent from its settings. Searching for a member follows the same rule everywhere you can search for one — the member list, the assignee picker, the initiative roster and an @-mention alike: you can always search a username, and full names alongside them in a guild that shows names. Typing a whole username with its number finds exactly that person. Notifications always name people by username, wherever they were written, because you read them away from the guild they came from.

- **Email addresses are no longer sent to guilds at all.** An account belongs to the person, not to the guild they work in, so a member's address no longer appears in the member list, member management, the member export, calendar invitations, or anywhere else inside a guild — members are told apart by their username, which is unique. Pending invitations show the address they were sent to partly hidden. Your own address is unchanged on your account page, and platform administrators still see addresses in the platform tools.

- **A closed account keeps its username.** Deleting an account still erases the name, address and picture behind it, but the username stays so that work it touched still says who did it — and an account whose username was assigned rather than chosen gets a made-up one in its place. Everyone deleted this way used to collapse into a single "[Deleted User]"; they no longer do.

- **An account is only ever changed by the person it belongs to.** Changing a password or an email address is now something only the account holder can do — the database enforces it, rather than each screen remembering to. A guild admin also no longer creates accounts with a password they choose: getting someone into a guild is an invite, so the password is set by its owner and stays theirs. Nothing in the app used the removed control.

- **Guild admins no longer edit member accounts.** A guild admin could previously change a member's display name and password. An account spans every guild its owner belongs to, so it isn't a guild's to edit: a guild admin now manages who is in the guild — inviting, approving, removing — and the account itself stays with the person and the platform admins. Nothing in the app used the removed control.

- **Each initiative settings tab has its own address.** Members, Roles, Properties, Export, and Danger zone are now real pages rather than tabs that reset when you reload, so you can link or bookmark one directly and the back button steps through them. Existing links to initiative settings still open where they always did. A notification about someone asking to join now opens the queue itself instead of the initiative's front page.
- **The Guild calendar app holds many calendars, not one.** Its sidebar entry now opens on every calendar the guild shares, overlaid in one view, and **any member can add another** — one for holidays, one for a recurring meetup, one for each person. Whoever makes a calendar owns it and decides its sharing, which starts as everyone in the guild can read it. The Calendars dropdown hides the ones you're not following, for you alone. The calendar the app arrived with is unchanged and still opens at its own address; removing the app sends all of its calendars to the trash together, as it always has for the one.
- **Comments are written in Markdown.** A comment body now renders the formatting you type into it — bold and italics, headings, bulleted and numbered lists, quotes, tables, links, and inline or fenced code, which stays literal rather than being formatted. Line breaks still land where you put them, and mentions of people, tasks, documents, and projects work exactly as before, including alongside formatting. Bare links are turned into links automatically, so pasted URLs no longer need to be wrapped by hand. An image is named as a link to itself rather than drawn in the comment, so opening it stays your choice. Existing comments are unaffected unless they happen to contain Markdown, which now renders. Comment previews — the guild home feed and a project's activity sidebar — render the same way, and they show mentions properly for the first time.
- **A long comment in the guild home's Recent comments can be read in place.** The feed shows the first two lines of each comment; one that runs longer now offers "Read more" beneath it, and "Show less" folds it back. Only comments that actually overflow get the control, and it re-checks as the column changes width. Mentions in the feed render as labels rather than links, so the whole entry stays a single click through to the comment.
- **The Cancel button sits beside Save when editing or replying to a comment.** It used to hang below the composer, away from the button it belongs with. Escape now backs out of an edit or reply too (once, if the mention list is open).
- **The Apps shelf only lists apps your server actually runs.** An app is served by a program the person running your server sets up — so a listing for one that they haven't set up yet, or have switched off, offered something that would install into nothing. Those listings now stay off the marketplace until the app is running, and adding one by hand is refused the same way. Dashboards are unaffected, and nothing changes for an app a guild has already installed.

### Fixed

- **A colour picker opened on red when the colour was black.** Black reads as no colour at all to the picker, so opening one on it showed red and could write that back over the colour you had. Black is now a colour like any other, wherever a colour is picked — tags, task statuses, initiatives, calendars, queue items, property options and the guild banner's fill.

- **Real names no longer appeared in a guild that shows usernames.** The rule reached the member lists and pickers but not the surfaces that carry a person alongside something else — a task's assignees, a comment's author, the latest comments on the guild front page, a project's activity, calendar attendees, queue rows, custom `user_reference` properties, dashboard filters and the data a custom widget is handed. All of them now name people the same way the rest of the guild does, including the cross-guild "my" lists, where each guild answers for its own rows. A comment also carried its author's email address, which no guild ever needed.

- **A guild admin could not turn "show real names" on or off.** Saving the setting failed outright. It is now on by default, so guilds keep showing names as before; a guild listed in the community directory still shows usernames and no longer offers the control at all.

- **Your username was missing from your own account page.** It sits under your email address now, shown but not editable, the same way your address is.

- **Rejoining a shared document no longer shows — or spreads — an outdated copy.** Coming back to a spreadsheet or whiteboard someone else kept editing could show the document as it stood when you left, until a page refresh; on spreadsheets, the outdated copy could even be pushed back into the live session and roll back the other person's work. Spreadsheets now wait for the live session's state before adopting any locally held copy, and whiteboards no longer treat another user's incoming edits as their own unsaved work — while correctly recognizing a live session when deciding whether local unsaved work should still win.
- **Dashboards that come with an app reach the marketplace.** An app whose listing bundles ready-made dashboards published them and then retired them again in the same pass, so they never appeared in a guild's dashboard picker. Both the shipped catalog and one an administrator adds now account for the dashboards each app declares. A dashboard an app stops shipping is still withdrawn, as before.
- **Editing an app service keeps the powers the form does not show.** The settings form rebuilt an app service's full list of granted powers from the controls it displayed, so saving an edit to an unrelated field — a base URL, an allowed origin — silently dropped anything else that had been granted. It now carries them through.
- **App and dashboard artwork now loads in the mobile app.** Marketplace listings whose artwork comes from the app registry — and the icons those apps show in the sidebar — were addressed as a path on the server, which the mobile app resolved inside its own bundle and drew as a broken image. They are now fetched from the server the app is signed in to.

## [0.63.4] - 2026-08-26

### Changed

- Adjusted the style of the personal space page headers.
- **Tab bars are consistent and fill their container.** The tab bars across the app — an initiative's tools, settings and admin sections, a tag's content, the sidebar's Initiatives/Tags switch, the document side panel, and the tabbed dialogs — were each sized differently: some hugged their labels, some stopped at a fixed width. They now share one component that spans the full width of whatever holds them, keeps each tab sized to its label, and scrolls sideways once the labels stop fitting. The view switchers on tool lists (table, board, grid, calendar) are unchanged — they stay sized to their icons inside the toolbar.

## [0.63.3] - 2026-08-26

### Added

- **Projects have saved filter presets, and a task view can be linked.** Every project now starts with four presets — All, Incomplete, Unassigned, and Mine — at the top of the task filters, and picking one puts it in the address bar, so a link shows a teammate the same tasks it showed you. The view (table, board, calendar) is linkable the same way. Edit the filters of a preset you are showing and it says so; "Reset to preset" puts them back. Project managers, the project's owner, and guild admins can save the filters currently on screen as a new preset for everyone, fold changes back into an existing one, rename or reorder them, and set which preset and which view the project opens on, under the project's Views settings. Everyone else picks from them and keeps their own filters as before.
- **Tasks can be filtered by whether anyone is on them.** The assignee filter gains "Assigned to me" and "Unassigned" alongside the people in it. Neither names a user — the server works out who is asking, and who nobody is — so a filter built on them means the same thing for whoever opens the link. Dashboard widgets can filter on unassigned work too.
- **The status filter can ask by category as well as by name.** Under the project's own statuses, the same dropdown now offers Backlog / To do / In progress / Done. Those ask about the *kind* of column rather than a named one, so a preset built on them keeps meaning the same thing in a project whose columns are named differently. Picking from both halves widens the list rather than contradicting itself.

### Changed

- **Due-date filters now apply everywhere the list does.** Filtering by overdue or due-soon was applied only to the visible list, so the board's per-column counts, the "archive done tasks" count, and CSV exports all quietly ignored it. The filter is now applied when the tasks are fetched, so everything agrees. "Overdue" now means due before today rather than before this exact moment.
- Adjusted background colors to reduce banding in Chrome based browsers.
- **A full guild no longer hands out invites.** When a guild has as many members as its user limit allows, the invite it would mint could only fail when someone tried to redeem it. Creating one is now refused, and both places an admin makes an invite — the guild's context menu and Settings → Users — say the guild is full instead of offering the action.

### Fixed

- **Several filter dropdowns had no name for screen readers.** The assignee, status and tag filters each sat beside a label that pointed at nothing, so all three were announced unnamed. They are now properly labelled, on project tasks and everywhere else those pickers are used.
- **The project page prefetched the wrong task list.** Opening a project prefetched tasks with filters that had drifted from the ones the page actually applies — it dropped tag and property filters and encoded the rest differently — so the prefetched result was never used and the list was always fetched a second time. Both now ask the same question.
- **Deleting a task drops you back in its project.** Confirming a delete on a task's page sent you out to the initiative's projects list, away from the sibling tasks you were working through. It now returns to the project the task was in.
- **Holding a guild on a phone opens its menu again.** Press-and-hold on a guild in the left rail was being taken as the start of a drag, so the guild menu — invite members, guild settings, leave guild — could not be reached by touch at all. Holding now opens the menu, and reordering has its own way in: pick "Reorder guilds" from that menu, or tap Reorder in the expanded guild list. While reordering, guilds can be dragged with a finger and a tap moves a guild instead of switching to it, until you tap Done. Reordering with a mouse is unchanged.

## [0.63.2] - 2026-08-25

### Added

- **Task and document tables remember how you left them.** The column you sorted by, the grouping you chose, and the columns you showed or hid now come back on your next visit — on a project's task list (kept per project, so one project's arrangement doesn't follow you into the next), My Tasks and Created Tasks, a tag's task list, and the documents list. My Tasks also stops claiming it is sorted by date window when your saved sort says otherwise. Settings and admin tables are unchanged: they are places you pass through, not arrange.
- **Documents and templates are listed separately, and the list filters by type.** An initiative's Documents tab now opens on a Documents / Templates toggle carrying each state's total, the way the projects list splits its own templates out; the templates view is linkable and answers the back button, and a tag's document browse lists documents only. The filter panel gains a document-type filter, so a list can be narrowed to text documents, files, whiteboards, spreadsheets or smart links; it counts toward the filter button's badge and Clear all.
- **An app being installed is an event.** A guild's installed apps now emit on the event bus like any other change — a webhook subscription can name `apps.created`, `apps.updated` and `apps.deleted`, and hear an install appear, its configuration state move, or it go away.

### Changed

- **Installed apps keep themselves up to date.** When a publisher releases a new version, your guild's install now moves to it on its own, so a fix arrives without anyone having to notice it exists. A guild that would rather read each version first can turn that off per app under Settings → Apps and update by hand from the same place — the button there names the version it will apply, and says "Up to date" when there is none. Apps you already have start out keeping themselves current. A version this server is too old to run is never applied, and neither is anything from a listing its publisher has withdrawn.

## [0.63.1] - 2026-08-23

### Fixed

- **Updating to 0.63.0 could stop partway with a database error.** The migration that gave every kind of content one `created_by` field also renamed the foreign keys named after the old field — but a guild created recently never had those keys to begin with, so the update failed on `constraint "calendars_created_by_id_fkey" for table "calendars" does not exist` and the app would not start. The rename now skips what a guild's schema does not have. An install stopped by this can simply update again; nothing was left half-applied.
- **The tag browser on a phone spilled over the documents behind it.** Opening "Browse by tag" on a narrow screen drew the whole tag tree past the bottom of its panel and on top of the document cards. The panel now keeps its tags inside it and scrolls, and its chevron turns over when it opens.

## [0.63.0] - 2026-08-21

### Added

- **Every tool has a comment thread.** Comments — previously only on tasks and documents — now live on projects, queues, counter groups, calendars, and dashboards too, guild calendars included. Whoever can see a thing can read and join its discussion, replies and @mentions work everywhere, the guild's recent activity feed carries the new threads, and the thing's creator is notified when someone comments.

### Changed

- **Tool lists have one control row on a phone.** A project or document list used to stack the create button, the import menu, the view toggle, a "Show filters" header and a lone Select button into four separate rows before the first card — on a phone the list started below the fold. Those controls now share a single row that stays put as you scroll: what's shown on the left, then filters, the view toggle, and an overflow menu holding import and Select. The filter panel starts closed and opens from the button — in a sheet from the bottom on a phone, rather than pushing the list down — and that button carries a count so a narrowed list still says so while the panel is shut. A Clear all button sits in the panel at every screen size, inactive when there is nothing to clear. Every list works this way — projects, documents, queues, counters, calendars and dashboards, a project's task list, a tag's tasks, and the cross-guild My Tasks, My Projects, My Documents and My Calendar. The create button drops out on narrow screens, where the floating add button already does the same job. An initiative's header shrinks to its name and settings gear with the description, badges and counts one tap away under Details, and a project card no longer repeats the initiative name on every card of that initiative's own list.
- **Projects, documents, queues, counters, calendars and dashboards now live inside the initiative they belong to.** Their addresses say so — a project reads as its guild, its initiative, then the project — and so do the tasks, events and counters beneath them. Because a list can only ever be one initiative's, the "filter by initiative" dropdown is gone from every one of them; the initiative you are in is the one you picked. A tool's tab is part of the address too, so you can link someone straight to an initiative's documents, reload onto the same tab, and use the back button through them.
- **Links you already have keep working.** A notification, a mention, or a queue item's linked entity resolves to wherever that thing now lives. Bookmarks and pasted links from before this change do not — the old addresses are gone rather than forwarded.
- **One name for who made something.** Every kind of guild content now records its author in a single field, `created_by` — replacing `author_id` on comments, `uploaded_by_id` on file versions, `installed_by_id` on installed apps, `created_by_user_id` on webhook subscriptions, `created_by_id` everywhere it already existed, and `created_by_user_id` on guilds and invites. A document's `updated_by_id` is gone — nothing read it, and who last changed a document is already recorded with the change itself. API clients reading the old field names need updating.
- **A document is named by `name`, like every other tool.** The documents API said `title` where projects, queues, counter groups, calendars, and dashboards all say `name`. The field, the list sort key, the upload form field, the linked-document rows on queue items and calendar events, and the export envelope now all say `name`; a comment's document context is `document_name`. Exports written before the rename still import. API clients reading or writing the old field need updating.
- **Every widget says where its data comes from.** A line under the title names the source, what it's narrowed to, and how many rows came back; click it for every filter in plain words, the display options, and a refresh. Names only ever resolve to what *you* can see.
- **Widgets can be filtered.** Status, priority, assignee, tag, project, any of the four dates, archived state, and title, with an optional "any of these" group. Dates can be relative ("due in the next 30 days"), so a dashboard never goes stale on the date it was saved.
- **Configuring a widget previews it.** The dialog runs the real widget against your own data while you choose.
- **Any widget can be read as a table** — a control in its header swaps the picture for the numbers.
- **The widgets do much more.** Stat shows a trend and a sparkline; chart gained ordering, a category cap, horizontal bars, a target line and highlighting; table shows assignees, tags, checklist progress and comment counts, marks overdue rows and totals columns; progress draws a meter per project; heatmap labels months and can count by creation or due date.
- **Charts read more cleanly** — lighter marks, room between bars, and a tooltip that leads with the value.
- **Widgets speak your language.** Their column headings and empty states were always English; marketplace widgets can now ship translations too.
- **Guild admins can transfer ownership of anyone's content.** Guild settings → Users has a Transfer ownership action on every member, moving everything that person owns in the guild — projects, documents, queues, counter groups, calendars and dashboards — to a chosen admin in one step. It works for people who have left as well as people who are still around, since accounts get abandoned as often as they get closed. This is the only place ownership is moved by hand, and only guild admins can do it.
- **Leaving a guild no longer hands your work to someone else.** Removing a member, leaving, or having access revoked used to make every project manager an owner of that person's documents and projects, or stop the removal until each project had been reassigned. Now it simply ends their access: what they owned becomes unowned, and guild settings lists it under Unowned content for an admin to claim whenever they choose. Anything already orphaned appears there too.
- **You can be removed from a guild even if you're the only project manager of an initiative.** That used to block the removal outright. Being a guild's last admin still does, since a guild needs someone who can run it.
- **A thing now has one owner, or none.** Ownership was recorded twice for projects and could name several people at once for anything shared, because the old hand-off made every project manager an owner. It lives in one place now, names one person or nobody, and never moves on its own.
- **Templates and archived projects are a filter on the projects list, not a second row of tabs.** An initiative page stacked two tab bars — one for the tool, another for Active / Templates / Archive. Now a single control above the list switches between Active, Templates and Archived, each showing how many it holds, so you can see there are three templates without going looking for them. The address bar remembers the choice (`?status=archived` is linkable and answers the back button). All three states render as the real project list: the same cards with icon, initiative, tags and task progress, the same search, tag, favorite and sort filters, the grid/list toggle, and bulk select for sharing and export. A template card carries a Template badge, an archived one shows when it was archived, and a button on the card un-templates or unarchives it in place.

### Fixed

- **A table bound to a spreadsheet range showed nothing.** Its columns were built without keys, so every cell landed in the same place.
- **Project progress was counted from a partial list.** Widgets read a fixed number of tasks at a time, so a larger project reported the wrong percentage. It now comes from the server's totals, and a widget drawing a partial list says so.
- **A widget whose data you can't see no longer tells you to configure it.** That prompt was shown both to authors who hadn't finished and to viewers whose access didn't cover the data; a failed load now reads differently again.

## [0.62.8] - 2026-08-19

### Changed

- **Webhook events now always name something you can fetch.** A project's statuses, a document's file versions, an initiative's roles, and a change to who a project (or document, queue, counter group, calendar, or dashboard) is shared with used to arrive naming an id with no endpoint behind it. Each now arrives as an update to the thing it belongs to — `projects.updated` with `statuses`, `documents.updated` with `versions`, `initiatives.updated` with `roles`, `projects.updated` with `sharing` — the same way a task's tags have always been reported. Every id in an event resolves to a resource you can read back.
- Document reads accept `?include_content=false` to return everything except the body. A document's body is by far the largest thing the API returns and usually isn't what changed, so a subscription reacting to an edit no longer has to fetch it.
- **Gantt widgets are now a proper project timeline.** The chart draws a line on today's date, so you can see at a glance what is behind and what is still ahead. Rows fold: bind one to Projects and each project is a single bar you can open to reveal its tasks, and a bar's fill is how much of the work under it is finished — a project that is halfway through its tasks is a half-filled bar, with the count beside its name. Bound to Tasks, you can group rows by project, status, priority, or assignee instead, and a total row across the top sums up everything shown.

### Fixed

- **Leaving a guild works again.** If you belonged to any of the guild's initiatives, leaving it failed outright with a permission error, and so did stepping out of an initiative you managed. Both go through now, and the change is still reported to any webhook watching.
- **The overdue digest no longer counts tasks you have set aside.** It swept up tasks in archived projects, and tasks you had archived yourself, so people were chased about work they had already cleared off their plate. The daily email and push now count only live tasks in live projects, matching what My Tasks has always shown.

## [0.62.7] - 2026-08-18

### Added

- **An app's page now matches your theme.** An embedded app is told your light or dark mode and your colors — color theme and guild accent included — when it opens, and again the moment you switch, so it can recolor in place instead of staying bright white inside a dark Initiative. Apps pick this up as they add support; one that hasn't yet simply keeps its own colors.
- **Outbound webhooks (API-only for now).** Register a URL via the API and Initiative POSTs a signed notification when content changes, filterable by event type and field. A subscription only ever delivers what its creator can access.
- Comments, subtasks, queue items and counters can now be fetched individually by id, and any resource can be fetched after it's been deleted with `?include_deleted=true` while it's still in the trash.

### Fixed

- **Breadcrumbs are now consistent everywhere.** Every project, document, queue, counter group, calendar, and dashboard page — and each one's settings page — now shows the same trail back to its initiative. Settings pages had dropped the initiative from the trail, and a counter group's page had no breadcrumb at all; both now match the rest.
- **The overdue digest no longer counts tasks in template projects.** Templates hold blueprint tasks whose due dates were never real deadlines, so anyone with a dated template project got emails and push notifications about work that did not exist. Only tasks in real projects are counted now.

## [0.62.6] - 2026-08-14

### Added

- **Android notifications now arrive on channels you can tune individually.** Comments, calendar events, event reminders, access requests, and the new overdue summary each get their own entry in the system notification settings, so you can silence one kind without silencing the rest — previously only five kinds were sorted this way and everything else arrived under a general heading. This part needs the updated app; the notifications themselves reach existing installs either way.

### Changed

- **An app is told who you are without being told which account you are.** Apps now know each member by an identifier unique to that app's own installation, rather than by an account id shared across everything. Two apps cannot compare notes and work out they are dealing with the same person, and an app installed in two guilds cannot link those guilds to one of your members.
- **The task-assignment digest now waits for the flurry to end.** It used to send on the first assignment and then go quiet for an hour, so a single task got an instant email while a batch of twelve arrived as one message plus a long silence — the opposite of what a digest is for. It now sends once nothing new has arrived for five minutes, or after thirty minutes if assignments keep trickling in. A lone assignment still reaches you promptly; a burst arrives as one summary.
- **Assignment email and push are the same message on the same schedule.** Push fired once per task, so twelve assignments meant twelve buzzes while your inbox got one summary. Both channels now ship together from the digest, and a summary covering one task still opens straight to it. The in-app bell is unchanged and still lists each assignment as it happens.
- Turning off the assignment email no longer stops push as well — the two toggles are now independent, as the settings page always implied.

### Fixed

- **Overdue tasks now reach your phone, not just your inbox.** The daily overdue digest was email-only despite the push toggle sitting beside it in notification settings, so anyone relying on the app for reminders never heard about overdue work. It now sends on whichever channels you have on, and turning the email off no longer silences the push. Tapping it opens My Tasks, since the digest spans every guild you are in.
- Push notifications sent by the app's own background work — the overdue and assignment digests, and access-request notices — reached the device and then failed while recording the delivery, which could leave a stale device registration in place after the phone had been handed on.
- **Un-assigning someone before the digest goes out now withdraws the announcement.** Previously the email still told them they had been assigned a task they no longer held.
- Sent digest entries are now cleared a week after the fact. Nothing had ever deleted them, so every task assignment ever made left a permanent row behind.

### Fixed

- **An app's page opens wherever the app is, however you got there, however long you have been signed in.** An app placed in an initiative now loads its page instead of an empty frame. So does one reached by clicking through the sidebar rather than by opening its address directly, and one opened after a long-running tab has been sitting idle. The browser permission an embedded app needs is now settled by which app services the deployment has connected, so it no longer depends on which page a tab happened to load first or on how recently you signed in.

## [0.62.5] - 2026-08-14

### Added

- **You decide whether an app may act as you.** A guild admin installing an app puts it in the guild; whether it may make requests in your name is a separate question, and now yours to answer — reads only, or reads and writes. Withdrawing takes effect on the app's next request, and leaving the guild takes it with you. Guild admins can see who has allowed what and end any of it, including everyone's at once without uninstalling the app, but cannot allow it on somebody else's behalf.
- **Every app has settings of its own**, reached from the gear beside its name in the sidebar. It shows what you control: your own answer about the app acting as you, and your own half of any connection — plus, for guild admins, what the guild owns, being the shared credential, where the app appears, and what each member has given it.
- **An app acts only in the guilds that installed it.** A delegating app reaching a guild now needs that guild's install to be present and switched on, alongside the power its registration grants — so uninstalling an app, or turning the install off, ends what it can do there without touching any other guild.
- **An app is granted the power to act as your members individually.** Delegation follows the app's own registration — its keys, its grant, its switch — rather than one setting shared by the whole deployment. Turning an app's delegation off, or turning the app off, ends what it can do straight away.
- An app service registration can hold the public keys its app signs delegation tokens with, as a JWKS — pasted into the registration form or declared in the app services file alongside the app's other settings. Two entries in one key set is how an app rotates its signing key without downtime, and clearing the field removes it.

### Changed

- An app's embedded page is granted only the browser features its manifest asks for, from a fixed list — camera, microphone, location, screen capture, clipboard, and fullscreen. A surface that asks for nothing runs with all of them denied. What an app requests is part of what it declares, so it can be read before installing.
- **A guild tells its members about the guild, and its admins about running it.** Everyone in a guild still sees its name, description, icon, member count, and whether content is currently read-only. The administration details — the storage and member limits set for the guild and its trash retention window — now reach guild admins only, matching the settings pages that are already theirs alone.

### Fixed

- **Dashboards render on a deployed instance.** Widgets are evaluated by a WebAssembly runtime that the served content policy did not admit, so every widget on every dashboard failed with a runtime error. The runtime's own bundle is now served with a policy that admits it; the policy the rest of the app is served with is unchanged.
- An app whose service stops matching what this deployment registered now stops offering its embedded pages, not only its data — the two halves of an app go quiet together. Both return on the next successful verification, and the app reads as unavailable meanwhile instead of opening a surface that cannot load.

## [0.62.4] - 2026-08-13

### Fixed

- An app's embedded surface now fills the page instead of sitting in a short box at the top.

## [0.62.3] - 2026-08-13

### Added

- Apps can now appear inside an initiative as well as guild-wide. An app that offers an initiative surface gets a row in each initiative's sidebar section, opening a page scoped to that initiative — the same install, told which initiative it is being read in.
- App surfaces name who they are for: everyone in the guild, an initiative's managers, or guild admins. An entry only appears for a reader it is meant for.
- **Dashboards have a settings page.** A dashboard can now be renamed, described, tagged, shared, and deleted like every other tool, from a Settings button on the dashboard itself.

### Changed

- **Every tool's settings page is the same page now.** Projects, documents, queues, counter groups, calendars, and dashboards share one layout — Details, Access, Advanced — with rename and delete always in the same place. Calendars pick up the tabbed layout the others already had, and whatever is particular to a tool sits alongside the common settings rather than replacing them: a project's schedule and task statuses, a counter group's duplicate, a calendar's color, a document's copies.
- Deleting a tool now names the thing being deleted, so the confirmation reads "Delete "Q3 Roadmap"?" instead of naming only its kind.
- An app service can now be wired up with a separate browser address. Its base URL is where Initiative's own server calls the app, so it may be an address only your network resolves; the new browser address is where a member's browser loads that app's embedded surfaces and connection pages. Leave it blank — the default, and what every existing registration keeps — and one address serves both, exactly as before.
- Guild admins choose which initiatives an app appears in, from the app's own settings. New installs appear in every initiative, which is the default.
- **Dashboard widgets are set in the same type as the rest of the app.** A widget's headline number carries the weight the figures on My Stats do, and a number that reads as good, cautionary, or bad is the same green, yellow, or red wherever you meet it. Labels, captions, table headers, and chart axis ticks now sit at one legible size instead of shrinking a step per widget.

### Fixed

- An initiative that renamed its managing role, or gave a second role manager standing, now sees the manager affordances it should: the sidebar reads the role's manager flag rather than looking for the built-in role by name.
- Pinning follows the same rule: a manager of an initiative can pin and unpin its projects whatever their role is called.

## [0.62.2] - 2026-08-13

### Fixed

- **The marketplace no longer offers an app that was removed.** A listing that ships with Initiative is taken off the shelf when a release stops carrying it, instead of lingering in the catalog of every instance that ever saw it — which is why the automation app could appear twice. A guild that already installed one keeps it; it simply stops being offered.
- **A listing shows the version you would get, not a history.** One app, one current version. Which version an install is running, and updating it, stay in guild settings where the app lives.
- **Installed apps open again.** Clicking an app in the sidebar did nothing. An app with a page of its own now opens it — with a tab for each view where an app offers several — and an app that only needs an account connected opens that form where you clicked, rather than sending you to look for it in guild settings. Apps that just feed widgets into dashboards have no page to open, so they tuck under a “show more” instead of taking up a row. Each app is now shown with its own artwork.

### Changed

- **Everyone can see the app store now.** The Apps section shows for every member, not only guild admins. A member gets “Browse the app store” where an admin gets “Add an app” — the same shelf, where each listing is tagged if your guild already has it, and one it does not says to ask a guild admin for it. Adding an app is still an admin's to do.
- **The sidebar drops “All Projects” and “All Documents”.** Both are a keystroke away in the command palette, and the space now belongs to your guild's apps. The apps list also matches the initiatives list above it — the same expand control, and “Add an app” sits at the bottom where “Add initiative” does.
- **A guild's front page is now a browser for its tools.** It was a fixed dashboard of personal statistics and activity cards — the same figures My Stats already gives you, mixed with a few shortcuts. In their place is a row of the guild's tools across the top: pick one and everything of that kind in the guild is listed underneath, whichever initiative it lives in, alongside that initiative, its tags, and when it last changed. Only the tools your initiatives actually use get a circle, and the tool you're looking at is part of the address, so the view can be bookmarked and shared. Underneath the list, the guild's latest comments carry on as before — they stay put whichever tool you're browsing, and each one links to the task or document it was left on.
- **Focus settings on My Tasks are now a window per priority.** Instead of one date range for everything plus an "always include urgent and high" switch, each priority gets its own slider: how many days ahead the Focus list looks for that priority, from today-and-overdue only up to a month out, or "any date" to keep that priority on the list whatever its deadline. Existing settings carry over.

## [0.62.1] - 2026-08-13

### Fixed

- Migration 162 frozen key error prevented migration from completing on v0.62.0

## [0.62.0] - 2026-08-13

### Added

- **A platform administrator can create a guild for another account.** The named account becomes the guild's admin and owns its first initiative, and the administrator who created it is left holding nothing in it. Everyone else creates guilds for themselves as before.
- **Dashboards.** A new tool inside an initiative: a canvas of widgets you drag and resize, reading that initiative's own projects and tasks. Seven kinds of widget — a headline number, charts (line, bar, stacked, area, pie), a progress bar, a funnel, a heatmap, a table, and a timeline — each with its own options, and a live preview while you pick one. Dashboards are read-only by design: they show work, they never change it. Sharing works like every other tool, so a dashboard can be yours alone, shared with named people or roles, or open to the whole initiative.
- **Counter board dashboard in the marketplace.** A scoreboard for whatever the initiative is tallying: one counter as the headline, its progress toward the goal, and the rest of its group charted alongside. Install it, then point each widget at the counters you want.
- **Event planner dashboard in the marketplace.** The initiative's events laid out the way an organizer thinks: everything on a weekly timeline, with the full event list underneath. Installs in one step and needs no setup.
- **Team activity dashboard in the marketplace.** A ready-made pulse of the initiative's people: work by person, the daily rhythm of completions, the open pile by priority, and the finished total as the headline. Installs in one step and needs no setup.
- **Apps, and a marketplace to add them from.** The marketplace is a searchable shelf of ready-made dashboards you can install into an initiative in one step, and of apps that add something the whole guild shares rather than any one initiative. The first app is a guild calendar: an ordinary calendar that belongs to the guild, visible to every member from the moment it is added, with the same views, event editor and sharing as any other. Apps live above your initiatives in the sidebar and are managed under guild settings, where they can be renamed, turned off, or removed — removing one moves what it created to the trash rather than deleting it. Only guild admins can add or remove apps; a guild with none installed shows nothing to its members.
- **The marketplace shows examples using sample data.** A listing's preview draws sample rows, so you see the shape of what you would get without it reading anything from your guild.
- **The app platform.** An app can now be more than something the marketplace lists: it can be a service your operator connects, which contributes widgets to dashboards, pages inside Initiative, and events. Your operator registers an app once for the whole deployment; a guild admin installs it and fills in whatever it asks for, and where an app authorizes people individually — the way GitHub does — each member connects their own account, so nobody borrows anyone else's access. Admins can see who has connected, and revoke or block any of it. Removing an app, leaving a guild, or closing an account takes the credentials with it. Some apps are provided by the platform and appear in every guild; those cannot be removed, and they say so.

### Changed

- **Sign-in and server-connection redirects are now decided before a page renders.** Landing on an app page while signed out, signing out, or opening the mobile app before a server is set now hands you straight to the right screen instead of briefly mounting the app shell and bouncing out of it. The old approach depended on that shell tearing down at exactly the right moment — the failure behind the blank page in 0.61.0.

### Removed

- **The advanced tool is gone.** The optional embedded panel an administrator could point at a companion service — configured with `ADVANCED_TOOL_NAME` / `ADVANCED_TOOL_URL`, switched on per initiative, and listed as a tool inside one — has been removed, along with its list, sharing, tags, trash entries and role permissions. What Initiative stored for it was a name and a sharing record around content the connected service already owned, and those rows are deleted on upgrade; the service keeps everything it holds. A deployment that wants a companion surface connects it through the app platform instead, which is the general form of what those settings were a single-purpose version of. The `ADVANCED_TOOL_*` settings are now ignored and can be dropped from your configuration.
- **The pre-0.53.5 copies of guild data in the shared database schema are gone.** Installs that predate 0.53.5 kept a frozen second copy of every project, task, document and so on from before guilds moved into their own database schemas. Nothing has read or written it since; upgrading now drops it. Guild data lives solely in that guild's own schema. Installs created on 0.53.5 or later never had these copies and are unaffected. **This upgrade cannot be rolled back** — take a backup first if you would rather keep the old rows around, and if you are upgrading from before 0.53.2, boot a 0.53.x release once on the way through as its startup notice instructs.

### Fixed

- **The Focus list on My Tasks stayed empty even with overdue work waiting.** It only counted tasks someone had moved to To Do or In Progress, and Backlog is where a new task starts — so on an ordinary setup it had nothing to show. It now looks at every unfinished task, whatever column it sits in. It also reads dates the way the task table beneath it does: work whose start date has arrived belongs on the list even if nobody gave it a due date.

## [0.61.3] - 2026-08-11

### Fixed

- **Completing a recurring task that carries tags failed with a server error.** Dragging such a task to a Done column (or otherwise marking it complete) returned a 500 and the next occurrence was not created. Only recurring tasks with at least one tag were affected, which made it look like a single project was broken.

## [0.61.2] - 2026-08-11

### Changed

- **Building a project from a template now reschedules its tasks.** Task start and due dates in a template are treated as relative: give the new project a start date and each task lands the same distance from it as it sat from the template's start — a task due three weeks in stays three weeks in. A template without dates of its own anchors on its earliest scheduled task, and giving only an end date anchors the schedule on the end instead. Leave the new project undated and task dates copy across unchanged, as before. Template task start dates, previously dropped, now carry over too.

## [0.61.1] - 2026-08-10

### Fixed

- **Signed-out visitors could not reach the sign-in page on 0.61.0.** Anything that landed on the app without a valid session — a first visit, a shared link, or a session that expired in a background tab — spun on a blank unresponsive page instead of redirecting, with no way to log in. The redirect away from the authenticated shell re-fired on every render, and a change in TanStack Router 1.170.19–1.170.25 stopped that redirect from settling, so it looped until the browser gave up. The router is pinned to 1.170.18 until the regression is fixed upstream.

## [0.61.0] - 2026-08-10

### Removed

- **The Gantt view has been removed from projects.** Task boards now offer Table, Kanban, and Calendar. Anyone whose saved view was Gantt lands on Table instead; nothing about the tasks themselves changes, and start and due dates are still shown in the Calendar view.

### Added

- **Spreadsheets can hold more than one sheet.** A tab strip along the bottom adds, renames (double-click a tab, or use its menu), duplicates, reorders, and deletes sheets — up to 64 per document. Formulas reach across sheets the way they do in Excel and Sheets: `=Sheet2!A1`, `=SUM(Data!A1:A20)`, and `='Q1 Actuals'!B2` for a name with spaces. Cross-sheet references keep working when things move — renaming a sheet re-spells every formula that named it, and inserting or deleting rows on one sheet shifts the references pointing at it from every other sheet. The name box also accepts `Budget!B4` to jump between sheets, and while typing a formula you can click a tab and then a cell to point at it. Excel export writes one worksheet per sheet; CSV, which can only hold a grid, exports the first sheet. Existing spreadsheets open unchanged as a single-sheet workbook.
- Tasks now record when they were completed. The timestamp is set when a task enters a Done status and cleared if it moves back out, so reopening a task no longer leaves it looking finished, and moving between two Done columns keeps the original completion time. Upgrading backfills tasks that are already complete from their last-modified date.
- **A Focus list at the top of My Tasks.** What actually needs doing now — work due soon plus anything urgent — with whatever you pin held at the top regardless of its dates. Ticking something off does not make it vanish: completions stay on the list, struck through, until the day turns over, alongside a running "3 of 6 done" count. Pin or unpin from either the list or the task table below it, set the date window and the urgent-work rule from the settings menu, and collapse the whole section if you would rather not have it. Every task matching your settings is shown, so a shorter list comes from a tighter date window rather than a hidden cutoff. The list spans all your guilds and is independent of the table's filters, so narrowing the table never empties it.
- **Projects can have a start and an end date.** Both are optional and independent — set either one, both, or neither when you create the project or later under Project settings → Details. When a project has dates they appear in bold at the top of the project page, next to its name and initiative; a project with no dates simply doesn't show the line. Duplicating a project or exporting and re-importing it carries the dates along.
- **Group a project's task table by tag.** "Group by" on a project's task list now offers Tag alongside Date window. A task sits under every tag it carries — one tagged both "bug" and "urgent" shows up in both groups rather than being filed under whichever tag came first — and tasks with no tags gather under Untagged. Each group is headed by the tag itself, in its colour. As with grouping by date window, manual drag-to-reorder pauses while a grouping is on; filtering, sorting, and bulk selection keep working, and a task selected in one of its groups counts once.

### Changed

- The linked-user picker on queue items is now a search, like every other person picker, instead of loading the initiative's whole roster up front.
- **Project settings → Details now saves everything at once.** The icon, name, description, and dates share a single "Save changes" button at the bottom of the tab, the way initiative settings already worked, instead of a separate save per section. Editing one section no longer discards unsaved edits in another. Tags still apply as you pick them.

### Fixed

- A start date later than the end date is now refused before saving, on both projects and tasks. The date pickers already stopped you choosing one, but a date typed into the field went through unchecked; the form now flags the range and keeps the save button disabled until it makes sense.
- Updated the document editor to Lexical 0.49, which brings table fixes (delete-line inside a cell, alignment applying both ways, and an optional sticky horizontal scrollbar on wide tables) along with selection fixes in read-only documents and in Firefox.
- Rebuilt every data table on TanStack Table v9. The tables themselves — task lists, document lists, the admin and settings tables — look and behave the same; the change is internal, moving sorting, filtering, grouping, pagination and selection onto the new feature-registration model. Row selection's "some rows selected" checkbox no longer stays half-ticked once every row is selected.
- Grouping a project's task table by tag no longer files every task under "Untagged". Picking a grouping from the toolbar moved the table but never told the page, so the page kept handing over its unfanned rows — none of which carry a tag to group on. Grouping by date window was unaffected, since those rows need no re-shaping.
- Dragging a card into a long Kanban column now changes its status. Once a column held more than about twenty cards the board drew only the ones on screen, and a drop into it could be credited to the last card the pointer crossed on the way in — so the card sprang back to where it started instead of moving. Columns that accumulate cards, Done most of all, were the ones affected.
- The calendar visibility dropdown no longer heads its list "My calendars". A calendar belongs to its initiative and is shared with the people in it, so the section is now simply "Calendars".
- Person pickers no longer show "User #12" where a name belongs. A selection the picker was handed rather than one you just made — the assignee filter you get back when you return to a project, a saved user property, the linked user on a queue item — is now resolved to a name and avatar against the same roster the dropdown searches. An id nobody in that roster matches still shows as an id, since there is no one to name.
- Pasting text that contains commas into a spreadsheet cell no longer splits it across neighbouring cells. Columns are now split on tabs only — the shape a spreadsheet writes when you copy a range — so a sentence lands in the one cell you selected. Pasted text with no tabs fills a single column, one row per line, matching how Excel and Sheets treat pasted CSV.

## [0.60.1] - 2026-08-06

### Fixed

- The 0.60.0 calendar migration failed on upgraded installs ("cannot drop column initiative_id of table calendar_events") because the pre-0.60 `recent_views` row-security policies still referenced that column. The migration now drops and re-renders those policies alongside the event-table ones; deployments stuck on the failed migration start cleanly on this release with no manual intervention.

## [0.60.0] - 2026-08-05

### Changed

- **The Events tool is now Calendars.** A calendar is a shareable container for events — like a project contains tasks — with its own name, description, and color. Sharing moves from individual events to the calendar: whoever can see a calendar sees its events, and whoever can edit it can create, edit, and move events inside it. Color belongs to the calendar too: events no longer carry their own color and always render in their calendar's. Attendees are unchanged (invitations and RSVPs stay per event) but never affect who can see an event. The calendar page lists your calendars alongside a derived, read-only calendar per project showing its task dates, each with its own visibility toggle. Existing events are preserved: every initiative that had events gets a renamable "Default Calendar" containing them, readable by all initiative members with initiative managers as owners — events that were previously shared more narrowly become visible to their whole initiative, so admins should move sensitive events into a restricted calendar after upgrading.

### Fixed

- Create buttons and initiative pickers for projects, documents, calendars, queues, and counter groups now consistently follow your actual per-initiative create permission. Members whose custom role grants creation see the affordances everywhere they apply, and buttons or picker entries the server would reject no longer appear.
- The calendar page now offers event creation in the all-initiatives view when you can write to at least one calendar — the create dialog picks the target calendar, defaulting to the one you used last.
- Platform staff acting in a guild through a scoped, time-bound access grant no longer see create buttons for new projects, documents, calendars, queues, or counter groups. Such a grant edits existing content only — the server already declined those creations, and the UI now reports the same answer instead of offering a dialog that fails on submit.
- The global "+" quick-create for documents and tasks (the bottom-bar menu and the command palette) now follows your create permission: its items hide when you can't create the thing in any of your guilds, and the wizards list only the guilds and initiatives you can actually create in — so you no longer walk through a wizard only to be refused on submit.

## [0.59.0] - 2026-08-03

### Changed

- **AI configuration is now connection-based with a single app-wide mode.** An operator chooses whether AI providers are configured at the **platform** level (the operator's connections apply to every guild), **per guild** (each guild admin configures its own), or **disabled** — one mode app-wide, mirroring the sign-in posture. A connection defines the provider, model, and an optional shared key; guild members attach **their own API key** and pick which connection they use, and never set the destination themselves. Standalone per-user AI (outside a guild) has been removed. An existing platform or guild provider is migrated into a connection automatically and its key is preserved; per-user AI keys are not migrated.

### Security

- AI provider credentials are now stored per member inside their guild's isolated database schema under row-level security, are never returned by the API (only whether a key is set), and are purged when a user is deleted or anonymized. A connection's destination (provider and base URL) is always set by the mode's owner, so a member's key is only ever sent to that owner-set destination. Every outbound AI call — subtask/description/summary generation, connection tests, and model listing — flows through the shared guarded egress that connects only to the policy-validated address; private or internal addresses are permitted only for an operator-configured local (Ollama) model, never for a guild admin or member.
- Personal API keys are now stored behind database row-level security and are reachable only through the system engine — the request path holds no grant on the table at all — matching the server-side session store. Creating, listing, deleting, and authenticating with API keys is unchanged.

## [0.58.3] - 2026-08-03

### Fixed

- The new-task dialog's **Status** dropdown now resets when you switch projects. Because the task section is reused as you move between projects, a status you had picked (or the previous project's default) could linger and be submitted against the new project, whose statuses have different ids. The composer now drops any status that doesn't belong to the active project and falls back to that project's default.

### Security

- Backup import now validates every upload asset key as a flat filename and uses one canonical key for its database lookup, uniqueness check, and storage write. A backup whose asset key carried path components is rejected as malformed, keeping an imported upload's database record and the stored file it points at in agreement.
- Hardened outbound webhook delivery and the custom AI provider so each request connects to the exact address validated against the target policy (https + public unicast); the original hostname is kept for TLS verification and the `Host` header. Both routes now share a single guarded egress helper.

## [0.58.2] - 2026-07-22

### Fixed

- The in-app MCP server's base64 filter now **nulls** `*_base64` fields instead of dropping the keys. Removing the keys made a tool's structured output violate its own (schema-required) shape, so every task or user-bearing listing failed with `'avatar_base64' is a required property`. The image blob is still stripped from the payload; the field is just kept as `null`.
- MCP list tools (tasks, `/me` tasks) now present their `conditions` and `sorting` parameters as JSON strings, so filtering and sorting through the MCP server work. They were typed as arrays (for the frontend), which the MCP request builder serialized with Python `str()` — single-quoted, invalid JSON — so every filtered or sorted list call was rejected with `QUERY_INVALID_CONDITIONS` / `QUERY_INVALID_SORT_FIELDS`.
- The cross-guild **My Tasks** / **Created Tasks** lists (`/me/tasks`, `/me/tasks/created`) now honor every `conditions` field — `due_date`, `title`, and the rest — instead of only a fixed handful (`project_id`, `priority`, `status_category`, `initiative_ids`, `guild_ids`, property values). Any other filter was silently ignored, so e.g. filtering "my tasks" by due date returned the full assigned list. The aggregate now applies the same filter set as the guild-scoped list, per guild.

## [0.58.1] - 2026-07-22

### Added

- The new-task dialog now matches the task editor: both are built on a single shared task form, so creating a task exposes the same fields as editing one. You can now set the **status**, attach **tags**, and fill in **custom properties** while creating a task — all saved in the single create request instead of only becoming available after the task exists.
- The single-project read (`GET /projects/{id}`) now includes the project's `task_statuses` (ordered by position), so a client has the status ids it needs to place or move a task without a second call or hunting through existing tasks. List responses stay lean and omit them. The MCP server also exposes the existing per-project task-status listing as a read tool.

### Changed

- In the task editor, tags and custom properties now save with the rest of the form when you click **Save** (previously they saved immediately on change). The editor warns before you navigate away with unsaved changes, and the new-task dialog no longer closes if you click outside it (use Escape or Cancel).

### Fixed

- The in-app MCP server now strips base64 image blobs (avatar and guild-icon data URIs) from every tool result. These `*_base64` fields carried no information an MCP client could act on yet often dwarfed the rest of a payload — a single guild icon was frequently larger than an entire task read — so filtering them out reclaims that context for the fields that matter.
- Relative timestamps across the app (e.g. "2 minutes ago" on task start/due dates, document cards and detail pages, comments, project activity, trash, import/export jobs, and the My Projects / My Documents lists) now refresh in place as time passes, instead of only updating on a page reload. A single shared clock drives every label, and each one re-renders only when its displayed text actually changes, so even large tables stay fast.

## [0.58.0] - 2026-07-21

### Security

- Platform role assignment is now enforced at the database layer: the request-path database roles carry column-scoped grants on the user table that exclude the platform role column, so role changes can only happen through the dedicated operator/owner role-assignment endpoint. Unused write privileges the request-path roles held on the user table were revoked outright. No behavior change for any existing flow; this is defense in depth, verified by CI invariants against the live catalog.
- Guild role assignment (promoting a member to guild admin) is now enforced at the database layer too. The endpoint runs on the system engine, and the shared guild database role no longer holds write access to change a membership's role — so a guild member cannot be elevated except through the guild-admin endpoint. Self-leave is scoped to your own membership, and request-path membership creation is pinned to a plain member. No behavior change for any existing flow; verified by CI invariants.
- Cross-guild access grants (the time-bound PAM / break-glass rows) can now only be written by the system-engine endpoints that already gate them by capability; the request-path database roles keep read access but no longer hold write access to the grants table. Defense in depth, verified by CI invariants.
- The per-guild and platform Postgres role-name prefixes (`GUILD_ROLE_PREFIX`, `PLATFORM_ROLE_PREFIX`) are now validated to identifier-safe characters at startup, so a misconfigured prefix fails closed at boot rather than reaching role-name DDL. Defense in depth (these come from operator config, not user input).

### Added

- Member pickers no longer download the entire guild roster: new slim, searchable, paginated endpoints serve member typeaheads (guild-wide, per-initiative, and per-project — the last scoped to the project's assignable write-access members), each returning just id, name, avatar, and status for a bounded page of results instead of every member's full profile. The assignee pickers (task edit, inline composer, bulk edit) and the assignee filter now search server-side against the project's members, the user-reference property picker searches its initiative's members, and the project/task pages no longer prefetch the full membership — so opening a project with thousands of members no longer transfers megabytes of inline avatars to render a dropdown. The task detail now carries its author inline (so the "Created by …" chip needs no roster lookup) and the trash owner-reassign picker lists the eligible owners returned with the prompt, so both drop their full-roster fetch too. Event attendee pickers (create dialog and settings) now use the same initiative-scoped typeahead. Mention autocomplete is server-backed too: the document editor's `@`-mention no longer loads the whole embedded member list (it searches the initiative's members on demand), the mention-search endpoint is now paginated in the same envelope as the other member searches, and both the document and comment mention pickers render member avatars.
- Multiple sign-in providers: the sign-in page now offers a button for every SSO provider the server has configured, not just one. Operators manage additional OIDC providers in Settings → Authentication — with presets for Google and Microsoft Entra, and a custom option for any OIDC identity provider (Keycloak, Authentik, Zitadel, …) — alongside the existing platform SSO form. Client secrets are write-only: set or replaced, never displayed.
- Per-guild authentication: on platforms configured for per-guild auth, guild admins get an Authentication tab to manage the guild's own OIDC identity providers (presets, write-only client secrets, and the guild's callback URL for IdP registration) and to require that members reach the guild only with a session signed in through one of them. An unsatisfied session gets a sign-in dialog that returns to the page it was on, and completing it upgrades the session in place — satisfying one guild never un-satisfies another. Requirements bind everyone (members, admins, and platform support alike) and are enforced in the database's row security across every surface — guild pages, cross-guild "my" views, realtime sockets (re-checked for the life of the connection), and media/download tokens — while long-lived integration credentials (API keys, device tokens, automation) deliberately never satisfy them. To prevent lockouts, an admin can only require a provider their own session has signed in with, and a required provider can't be deleted until the requirement changes. Outside per-guild auth posture the surface is absent entirely. Each guild also gets a shareable sign-in page (`/guild/{id}/login`, linked with a copy button from the Authentication tab): signing in through the guild's IdP admits the user to the guild as a plain member — provisioning their account on first sign-in when the provider allows it, honoring the guild's member capacity — so a single-guild user's entire login experience can live at their guild.
- Per-guild sign-in is now an operator entitlement. On per-guild-auth platforms the platform Guilds dashboard gains a per-guild toggle that turns a guild's Authentication surface on or off (the guild's own admins can't grant it themselves). Turning it off is non-destructive: the guild's providers are kept and existing members keep signing in through them — and any existing sign-in requirement stays enforced — it only closes the guild's auth-config surface and stops new accounts onboarding through the guild's IdP. The toggle appears only under per-guild auth posture.

### Changed

- The platform single sign-on configuration now lives on its provider-registry entry — the same registry that backs additional and per-guild providers — instead of a parallel copy in app settings kept in sync behind the scenes. The settings page, login, and background sync all read one record now; the migration folds any existing configuration in automatically and the settings screen is unchanged. `OIDC_*` environment values still pre-fill the provider on first boot only.
- Accounts created through single sign-on no longer carry an unusable placeholder password — they store no password at all, and password login for such an account is simply refused until one is explicitly set. The legacy per-user OIDC columns (superseded last release by the per-provider identity links) are dropped; the migration re-copies any not-yet-migrated data first, so upgrades that skipped a release lose nothing.
- Login posture (platform-wide vs per-guild sign-in) is now a deploy-time setting (`AUTH_SCOPE`), read once at startup, rather than a runtime toggle in platform settings. The Authentication settings page shows the active posture as a read-only badge; the "coming soon" per-guild radio and its endpoint are gone. Posture is infra-agnostic — nothing about a specific host or vendor is baked in.
- The sidebar and the initiatives landing page no longer download every document (and, on the landing page, every project) just to show per-initiative count badges. New grouped-counts endpoints return the per-initiative totals in one query, honoring the same visibility rules as the lists — so the badges stay accurate while large guilds stop transferring their whole corpus on every page. The sidebar's queue and counter-group badges use the same endpoints now too, replacing capped list fetches that silently undercounted past 100 items and dragged each item's full sharing state along.
- The "new document" and wikilink dialogs no longer download every document in the guild to populate their template picker. Both pickers are now searchable typeaheads backed by the server: templates are filtered in SQL (by template flag and document type) and searched by title across the whole guild, so opening the dialog fetches a bounded page instead of the entire document corpus. Picking a template for a whiteboard or spreadsheet no longer lists text-document templates. The documents list gained the same filters for callers that need them.
- The guild projects list no longer loads every visible project's full object graph just to filter and paginate it in Python. The `archived`/`template` filters, ordering (per-user manual order), and pagination now run in SQL, so a page fetches only the rows it returns and the reported total is exact rather than truncated. A `search` param (name substring, matching the "my projects" list) and an opt-in `slim` projection (id, name, icon, initiative, and your permission level — without documents, grants, tags, or the nested initiative) let project pickers and similar list-only callers fetch a bounded, lightweight page.
- Task pickers no longer download full task rows just to show a title list. A new slim task typeahead (id + title, searched by title in SQL and scoped to an initiative or the whole guild) backs the queue item's linked-task picker and the command palette's task search, so each keystroke fetches a bounded, lightweight page instead of every matching task's assignees, status, tags, properties, and comment counts.
- Sidebar rows use their full width: an initiative, project, or tool row's name and count now span the whole row until you hover it, at which point the settings/"+" button slides in and the name shrinks to make room (rather than the button permanently reserving space or overlapping the text). The reveal animation is skipped for users who prefer reduced motion.
- Export menus in tool headers now group their formats under a "Backup" heading (the importable JSON envelope) and a "Report" heading (PDF, CSV, Excel, Markdown, and other renderings), so it's clear which download can be re-imported.
- Calendar pages now load events and task markers in a single request instead of two. New `calendar-entries` endpoints (per-guild and cross-guild "my calendar") return the union of calendar events and in-window task start/due markers over the visible date range, each leg still gated by the same per-resource access rules as the standalone lists. The Events page and My Calendar consume the aggregate through one query; My Calendar now also windows its tasks to the viewport and shows every in-window task rather than only the first page.

### Fixed

- Signing in through single sign-on no longer sends the app into a request storm: the sign-in callback finished, updated the session, and then re-ran itself off its own update, re-fetching the current user, the guild list, and access grants dozens of times before settling. The callback is now consumed exactly once, and the guild list no longer reloads every time the current user is refreshed.
- Comment, document-summary, and guild-list error messages now route through the shared error-message helper: the user sees a localized message (and rate-limit errors are surfaced as such) instead of an untranslated backend error code.
- A database created or restored in a Postgres cluster where the platform "admin" → "operator" role rename had already run no longer loses its platform-staff row-security coverage: a repair migration finishes the rename by re-binding the affected policies (access-grant queue, platform user list/management) to the operator role and removing the leftover one. Without it, operators and owners saw only their own rows in the access-grant queue and the platform user list on such databases.
- The sidebar "Edit tag" dialog is no longer visually broken — the name field now fills the row and the color picker sits beside it, instead of the color picker taking the full width and collapsing the name field to a sliver.
- On mobile, opening the three-dot menu next to an initiative or project in the sidebar no longer dismisses the sidebar drawer.
- Removed redundant spacing between icons and labels across buttons throughout the app; the button's built-in gap now handles it consistently.
- The "My Tasks" page no longer returns a 500 error when filtered by a custom property. The cross-guild task views load property definitions per guild schema now, instead of querying a table that isn't visible on that request's connection.
- The dashboard's "Upcoming tasks" list no longer sorts urgent tasks last. It sorted by a hand-rolled priority map that omitted `urgent` (and invented unused `critical`/`none` keys), so every urgent task fell into the fallback bucket and sorted after lower-priority ones. Priority ordering now flows from a single source of truth in `lib/sorting.ts`, derived from the backend `TaskPriority` enum, that every priority-list UI shares — so it can't drift again.
- The "My Documents" page's data fetching now routes through the shared API client wrapper like its sibling "My Projects"/"My Calendar" views, instead of a hand-rolled fetcher that bypassed it — so native (Capacitor) base-URL rewriting and request handling apply consistently.

## [0.57.0] - 2026-07-16

### Added

- Tags on every tool: queues, counter groups, and advanced tools can now be tagged, joining projects, documents, calendar events, tasks, and queue items. Each tool's settings flow gained a tag picker, its lists show tag chips, and tag support is now wired automatically for any future tool (drift-tested against the tool registry).
- Bulk tag edit is a single atomic operation: one request adds/removes tags across the whole selection server-side. A failure (for example a tag someone else just deleted) changes nothing — no more half-applied batches — and a bulk edit no longer floods other viewers with one refresh per item.
- Sidebar tag editing: a pencil toggle in the Tags header switches the sidebar tag browser into edit mode — rename, recolor, or trash any tag inline, with a select-all checkbox and bulk delete — no need to visit each tool that uses the tag. The separate expand-all/collapse-all buttons merged into one toggle.
- Backup restore: a whole initiative or guild backup zip can be imported by a guild admin. Upload shows a pre-flight plan (source guild, per-initiative content counts, file payload size) before anything is applied; confirming restores each backed-up initiative as a NEW initiative (renamed on collision, tool switches from the backup, the importer becomes its manager), with uploaded files restored into guild storage (deduplicated and quota-checked) and every entry applied through the same importers as single-file imports — a corrupt entry fails alone and is reported, never the whole restore. Unconfirmed uploads expire after 24 hours.
- Data import: every exported JSON envelope — projects, documents (text, spreadsheet, whiteboard, link), queues, counter groups, and calendar events — can now be imported into an initiative of your choice. Tags and custom properties match by name (or are created), people resolve by email against the target initiative's members with unmatched ones reported, and the importer becomes the owner of everything created. Small files import instantly; large ones run as a background job with an inbox notification when done. Requires the tool's create permission in the target initiative; 0.56.x-era exports (the old `kind` spelling) import unchanged.
- Import surfaces: each tool's list page (documents, projects, queues, counter groups, calendar) gained an "Import from file" action — an overflow menu on the header and a button in the empty state — for importing that tool's JSON export. The backup import runs through a wizard in guild settings: pick a zip and it's previewed locally (nothing uploaded until you continue), then uploaded, planned, and confirmed.
- Guild settings **Data** tab: the former Export tab now hosts both directions — export and import — plus one activity table showing recent export and import jobs together, with re-download for finished exports and a report view for finished imports. The old `/settings/export` URL redirects here.

### Fixed

- Startup no longer fails with `permission denied for table guilds` (or, before 0.55, `new row violates row-level security policy for table "guilds"`) on installs that still have `PREVIOUS_SECRET_KEY` set. The boot-time secret-key sweep left an assumed per-guild database role on a pooled connection after committing, which blinded the startup seeding that ran next — it saw no guilds, tried to re-create the default one, and crashed the boot. The role is now transaction-scoped in the rotation sweep, the S3 upload backfill, and the local-upload relocation walk, so it can never outlive the work it was assumed for.
- Bulk tag edits could partially apply and error when the selection was edited from a stale view (for example after another member deleted a tag); the resulting event storm could also degrade the whole server.
- The tag list shown on tasks, projects, and documents right after saving tags now always reflects the save (it could briefly show the previous tags).
- Duplicating or cloning tasks, projects, and documents no longer carries over links to tags sitting in the trash.
- The documents "untagged" filter and count now treat a document whose only tags are trashed as untagged.
- Renaming or recoloring a tag now refreshes its chips everywhere immediately; deleting a tag refreshes all tools' lists, not just tasks.
- Imports now match existing tags case-insensitively, matching the duplicate rule the tag editor enforces.
- The calendar no longer drops tasks. It asked for the first 100 tasks in the initiative with no date filter at all, so a busy initiative could silently leave in-window tasks off the calendar entirely, while still transferring tasks from years you weren't looking at. It now fetches exactly the dates the current view shows (day, week, month, year, or list) and pages through all of them. The project filter's options now come from the initiative's projects, so they no longer appear and disappear as you move between months.

### Changed

- Startup now logs which Postgres login each of the three database connections uses, and warns loudly (without refusing to boot) on wiring that collapses the role separation: `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` sharing a login, or the app login holding SUPERUSER/BYPASSRLS (for example, swapped connection strings). It also verifies the connected logins actually hold the audited shared-table privileges — a deployment connecting as non-standard logins now stops at boot with the exact `GRANT` statements to run, instead of failing later with a bare "permission denied" mid-request or mid-seeding. Creating the default primary guild in a database that shows signs of not being fresh (existing users or surviving guild schemas) now logs a warning naming the likely causes.
- The document and task pickers on queue items, and the project's "attach existing document" picker, now search as you type on the server instead of downloading every document and task in the initiative when the dialog opens. Opening a picker shows the most recent entries and typing narrows them; large initiatives no longer stall these dialogs. Project document cards now load only the documents actually attached (API: `GET /documents/` gained an `ids` filter, max 100 per request).
- The web app now renews your session silently in the background instead of interrupting you with a "session expired" sign-out when the short-lived access token lapses. You stay signed in as long as you use the app at least once every 30 days; signing out still ends the session everywhere immediately.
- Signing in (password or SSO) now issues the short-lived renewable session token directly, completing the new login model: the browser session rides the rotating refresh token instead of a single hour-long token. If the session store is briefly unavailable, sign-in falls back to the legacy token so nobody is locked out. Changing your password now keeps the device you changed it on signed in, while still signing out every other session immediately.
- Single sign-on account data (the IdP subject, refresh token, and sync timestamp) now lives on the per-provider identity links instead of the user row; a boot backfill migrates existing data automatically and nothing changes for signed-in users. The API's `UserRead.oidc_sub` field is replaced by a `has_federated_identity` boolean (read by the profile and deletion dialogs to hide the password confirmation for SSO-only accounts).
- The project import dialog now uses the shared import engine (API: `POST /projects/import` was replaced by `POST /imports/envelope`, which accepts every tool's envelope — the file's `type` field selects the importer).

## [0.56.1] - 2026-07-14

### Changed

- Export envelopes and backup manifests now use a `type` field as their format discriminator instead of `kind` (values unchanged, no schema version bump), and project backups carry `type: "initiative-project"` like the other tools. Files exported by 0.56.0 still import: the editor's import accepts both spellings, and project backups never depended on the field.

## [0.56.0] - 2026-07-14

### Added

- Data export: every tool — documents, projects, tasks, queues, counter groups, and calendar events — can be exported straight from its page in type-appropriate formats.
  - Report formats: PDF (set in the app's typeface, with the guild's name and icon in a running header), CSV, Excel (XLSX), Markdown, and Word (DOCX) for text documents. Report content is localized (English, German, Spanish, French) and timestamps use your time zone.
  - Importable backups: JSON envelopes for text documents, whiteboards, spreadsheets, smart links, projects, queues, and counter groups (each carrying the entity's tags and custom properties where it has them), and the original file for uploads. A whiteboard envelope's content is a standard Excalidraw file, so unwrapping it opens anywhere Excalidraw runs. The editor toolbar's import accepts both the envelope and legacy `.lexical` files. Whiteboards additionally export PNG/SVG images, rendered in the browser.
  - Tasks export the current view — same filters and visibility as on screen, or just the selected tasks — as a table, a checkable Markdown task list, or a detailed one-task-per-page PDF carrying the full record: description (rendered as Markdown), subtasks, threaded comments, assignees, tags, and dates. Queues export their turn order with current/held/hidden entries marked; counter groups export their values and bounds.
  - Bulk selection: select multiple documents, projects, queues, counter groups, or calendar events and export them all at once. The documents grid and tag views gained the same card selection (and full bulk toolbar) as the other lists.
  - Calendar events export as a standard iCalendar (.ics) file (recurrence rules and attendee RSVPs preserved) or an importable JSON envelope — for a selection, one initiative, or every event you can see. Event sharing rules apply throughout: an export only ever contains events shared with you.
  - Delivery: small exports download instantly; large ones run as a background job, and an inbox notification delivers the file if you navigate away. Artifacts are private to their creator (guild admins can see their guild's), expire after 7 days, and spreadsheet formats carry injection protection. Read access suffices everywhere except project backups, which require write.
  - Whole-initiative and whole-guild exports: one zip containing either an importable backup — every tool's JSON envelope in per-initiative folders, indexed by a manifest, optionally bundling the file uploads your documents reference — or an à-la-carte report with a per-tool format choice (a project PDF beside a queue CSV beside a calendar ICS). Guild-wide export is guild-admin only (re-checked when the job renders); sharing rules apply within each initiative, projects you can only read are included in backups, and a pre-flight estimate reports per-tool counts and the uploads payload size.
  - Export wizard: an Export tab in initiative settings (managers and up) and a new Export tab in guild settings (admins) walk through those exports — pick backup or report, toggle tools with live item counts, see the uploads footprint before committing, and choose report formats per tool (documents split by text/spreadsheet type). Exports run in the background; closing the dialog doesn't cancel them.
  - The guild settings Export tab also lists recent exports (guild admins see every member's), so finished artifacts can be re-downloaded until they expire — no more losing a download to a closed tab.

### Changed

- Project backup (JSON) export now runs through the export engine: large projects export as a background job with the inbox-notification pickup instead of one long request, and artifacts follow the same private-to-creator delivery and 7-day expiry. The downloaded file and the import flow are unchanged. (API: `GET /projects/{id}/export` was replaced by `GET /exports/project?project_id=…`.)
- The calendar's ICS export moved onto the export engine (API: `GET /calendar-events/export.ics` was replaced by `GET /exports/calendar-event?format=ics`); the cross-guild `/me/calendar-events/export.ics` feed is unchanged.
- The queue page header now matches the other tool pages: a labeled Settings button sized like its neighbors, with queue deletion living in the settings page (where it already had a confirm dialog) instead of a header trash icon.
- The app's font (Outfit) is now bundled with the app instead of loaded from Google Fonts, so pages render without contacting any third-party host — including on air-gapped or intranet deployments.

### Fixed

- The advanced tool's Create button now works. The sidebar "+" and the "New Advanced Tool" button (in the tool tab) were previously a disabled placeholder; they now open the connected tool's embedded page on its new-item screen, where the tool is built. Nothing is created on our side until it's saved there.
- Guild admins can now load the member roster of initiatives they haven't joined. The roster API returned 403 for them — every other initiative read already honored the guild-admin override — which left the linked-member and assignee pickers empty when an admin viewed another member's initiative.
- Boot now heals missing shared-table grants for the system engine. Startup now re-asserts the audited `system_grants` registry for `app_admin`/`app_user` (tables and their row-id sequences), idempotently and additively — completing the issue #835 fix.
- The editor's emoji picker no longer breaks when the search text contains characters like `(` or `[`, and suggestions now match on the emoji's name as well as its keywords.

### Security

- All GitHub Actions in the CI/release workflows are pinned to full commit SHAs.
- Chart theme styles are validated by the browser's own CSS parser before being applied (defense in depth; no user-facing change).

## [0.55.0] - 2026-07-12

### Added

- Per-guild user limits (default unlimited), set from the admin dashboard's Guilds tab. At the cap, new joins/invites are refused; existing members and SSO auto-provisioning are unaffected.
- Per-guild lifecycle status for moderation holds: `read_only` blocks writes, `suspended` hides the guild from members (admins keep settings access). Reversible; never touches stored data.
- Support/moderator access grants are now database-enforced: read grants are read-only; read_write grants can edit content but not membership, roles, or sharing.

### Changed

- Renamed the platform **Admin** role to **Operator** so it no longer collides with a guild's **admin** role. The platform ladder is now `member → support → moderator → operator → owner`; capabilities and behavior are unchanged. A migration renames the `users.role` value and the `platform_admin` database role in place, so existing platform admins become operators automatically — no action needed.
- Operator "delete this guild" is now scoped to the deleted user's solely-admined guild instead of accepting any guild id.
- Removed the `ALGORITHM`, `COOKIE_NAME`, `REFRESH_COOKIE_NAME`, `PROJECT_NAME`, and `API_V1_STR` settings — their values are now fixed. Drop them from your `.env`; leftovers are ignored.
- Removed the `OIDC_REDIRECT_URI` and `OIDC_POST_LOGIN_REDIRECT` settings (read by nothing — redirect URLs derive from `APP_URL`) and the legacy `OIDC_DISCOVERY_URL` alias. OIDC is configured in Settings → Admin; the `OIDC_*` env vars only pre-fill it on first boot. If you still set `OIDC_DISCOVERY_URL`, use `OIDC_ISSUER` instead.
- `backend/.env.example` was rewritten; optional OIDC/SMTP/S3 lines are commented out so placeholder values no longer seed the admin settings on first boot.
- SSO (OIDC) sign-in now fully verifies the provider's identity token (signature, issuer, audience, expiry, nonce) and links accounts by the provider's stable subject id instead of email. No action needed; existing logins keep working.

### Deprecated

- A superuser (or `BYPASSRLS`) role in `DATABASE_URL` is deprecated; a future release will refuse to start with it. To migrate: run `backend/scripts/create-provisioner.sql` once (`-v provisioner_password='<password>'`), point `DATABASE_URL` at `app_provisioner`, restart. Fresh docker-compose installs already do this.
- Removed the unused `AUTO_APPROVED_EMAIL_DOMAINS` setting (read by nothing). Drop it from your `.env` if present.
- Removed the `MAX_UNBOUNDED_PAGE_SIZE` setting — "fetch all" list responses are now served in bounded windows that the app pages through automatically, so there is nothing to tune. Drop it from your `.env` if present.

### Fixed

- Deleting a user's blocking guild from the admin user-deletion dialog no longer freezes the page (and silently does nothing): the UI dependency tree carried three copies each of Radix's focus-scope, dismissable-layer, and focus-guards packages, so the nested confirm dialog and the outer dialog couldn't see each other — fighting over focus in an infinite loop, dismissing each other on clicks, and leaving the page permanently unclickable. Each is now pinned to a single copy, which also protects every other nested dialog/confirm combination.
- Guild admins of a suspended guild are no longer trapped on its settings page: the redirect that pins a suspended guild to settings fired against the pending navigation target, cancelling every attempt to reach another guild or a personal page. It now only applies within the suspended guild's own routes. PAM/break-glass grantees are exempt from the pin entirely — a grant browses a suspended guild like an active one (the backend never blocks grant access on lifecycle status), so grantees now reach its content instead of being stranded on a settings page they can't view.
- Read-only guilds no longer offer create buttons the server would refuse: documents, projects, queues, counter groups, and events hide their create affordances while the guild is frozen. Queue, counter, and event error toasts now surface the actual reason (e.g. "Guild access denied") instead of a generic "something went wrong".
- Newly registered users are no longer bounced from the home page to the documents page with the "create document" dialog open: the create-document wizard's auto-advance no longer runs while its dialog is closed. The create-task wizard shared the same defect (silently pre-fetching and advancing while closed) and was fixed alongside it.
- Task boards, document pickers, and project lists with more than 1000 items no longer silently lose rows: "fetch all" list requests now walk bounded server windows until the complete set is retrieved, and truncation is always reported via `has_next`.
- `backend/scripts/create-provisioner.sql` missed the per-guild support roles: after switching `DATABASE_URL` to `app_provisioner`, deployments with existing guilds failed to boot with `permission denied to grant role "guild_N_support"`. If that hit you, run the fixed script once against your app database, connected as the Postgres superuser: `psql -v ON_ERROR_STOP=1 -U <superuser> -d <app-db> -v provisioner_password='<your password>' -f backend/scripts/create-provisioner.sql`. Running it again on a healthy install changes nothing.
- Guild storage caps, member limits, tier label, and lifecycle status can no longer be edited through guild-facing settings — they are platform-operator inputs, now enforced with column-scoped database grants.
- Anonymizing or deleting a user now scrubs their email from guild invites addressed to them, and neutralizes the invite so it can't become an open shareable link.
- Startup no longer fails with an RLS error when `DATABASE_URL_ADMIN` has lost its `BYPASSRLS` attribute (typical after restoring from a dump, #835): boot restores it automatically when possible, and otherwise prints the exact `ALTER ROLE` command to run.
### Security

- Block guild admins from changing a user's account `status` through the generic `PATCH /g/{guild_id}/users/{user_id}` edit endpoint. The handler already rejected platform `role` changes there, but `status` fell through to the field-assignment loop, so a guild admin could deactivate or anonymize any co-member — including the last platform admin — bypassing the dedicated deactivate/reactivate flow and its guards (last-admin protection, ownership transfer, confirmation). Status changes now return HTTP 400 and must go through the delete/approve endpoints.

## [0.54.2] - 2026-07-04

### Fixed

- **Notifications work again.** The 0.54.0 least-privilege database refactor revoked the bare login role's access to the `notifications` and `push_tokens` tables, but the notification and push-token endpoints still ran on that role — every request failed, so the bell showed no notifications (the backlog looked cleared; it was never deleted and reappears with this fix), nothing could be marked read, and mobile push registration failed. These endpoints now run on the authenticated platform path like the rest of the API, and unregistering a push token is scoped to the calling user's own tokens.
- Permanently purging a document (manual trash purge or the retention worker) now unresolves wikilinks pointing at it in every other document — including trashed ones — instead of leaving links that reference a document that no longer exists.
- Expired sign-in and verification tokens are now cleaned up automatically by an hourly background sweep; previously expired rows accumulated indefinitely.
- Deleted (anonymized) users now display consistently as "Deleted user" everywhere; several screens previously showed a raw email or "Anonymous".
- Anonymizing a user now scrubs their display name out of content that embedded it as text — @-mentions in comments, mention nodes in documents, and pending assignment-digest emails — instead of leaving the name readable after the account was "forgotten".
- Hard-deleting an already-anonymized user now removes their guild-scoped data (task assignments, sharing grants, authored-content reassignment, …). Anonymizing drops guild memberships, and the deletion sweep only visited membership guilds, so it silently skipped everything.

## [0.54.1] - 2026-07-04

### Added

- Calendar events now appear in the recent-items tabs bar, like projects, documents, queues, and counter groups.
- Calendar events and the advanced tool now appear in the command palette (⌘K) — events are searchable like other tools; the advanced tool gets one jump entry per enabled initiative.
- Initiative pages have an advanced-tools tab listing the initiative's advanced tools, with the standard Select → Edit access bulk-sharing flow (creation still happens in the connected automation service, and the UI says so).
- Counter groups can now be created from the mobile initiative menu, matching the other tools.
- Hard-purging an advanced tool (manual trash purge or the retention worker) now notifies the connected automation backend so its scheduling mirror is deleted too — including tools swept away by an initiative purge. Configured via `ADVANCED_TOOL_BACKEND_URL` + `ADVANCED_TOOL_PURGE_SECRET` (HMAC-signed, best-effort; unset on the default OSS image). Soft delete and archive stay pull-based — the automation side discovers them by syncing.

### Changed

- **Canonical tool naming across the API (breaking, pre-v1).** Every per-tool name now derives from one canonical tool enum: initiative master switches (`events_enabled` → `calendar_events_enabled`, `counters_enabled` → `counter_groups_enabled`, `advanced_tool_enabled` → `advanced_tools_enabled`), role permission keys (`docs_enabled`/`create_docs` → `documents_enabled`/`create_documents`, `create_events` → `create_calendar_events`, `create_counters` → `create_counter_groups`, `create_advanced_tool` → `create_advanced_tools`), and the per-member permission flags (`can_view_docs` → `can_view_documents`, `can_view_events` → `can_view_calendar_events`, `can_view_counters` → `can_view_counter_groups`, `can_view_advanced_tool` → `can_view_advanced_tools`, plus the matching `can_create_*`). A guild migration renames the columns and rewrites stored permission keys; no compatibility shims. The advanced-tool embed handoff now reads `advanced_tools_enabled` and the `create_advanced_tools` claim — external embed backends must follow the rename.
- Permission keys, initiative switch fields, membership permission flags, and recents entity types are now all derived from the tool enum in code (with CI drift tests), so adding a tool wires every backend surface automatically.
- The frontend now defines each tool in ONE registry (`src/lib/tools.ts`) — an icon plus capability flags — and derives everything else from it (routes, i18n keys, permission keys, sidebar rows, command-palette groups, initiative tabs, recents, trash invalidation), with drift tests that fail naming exactly which surface a new tool is missing. Route URLs renamed to the canonical stems: `/events` → `/calendar-events` and `/my-calendar` → `/my-calendar-events` (no redirects, pre-v1).

### Fixed

- Trashed counter groups and counters now auto-purge after their retention window, like every other trashed item — previously they lingered in the database indefinitely once past retention.
- Restoring an item from the trash now refreshes the relevant list pages immediately — the restore invalidation used cache keys that didn't match the app's real query keys, so restored items only reappeared after a manual reload.
- The calendar event attendee picker no longer comes up empty. It now lists the initiative members who can access the event.
- Clearing the initiative filter (e.g. clicking "All Documents") now resets to every document without a manual refresh.
- Break-glass / PAM access now shows the granted guild in the switcher immediately, instead of requiring a page reload before the guild becomes reachable.

## [0.54.0] - 2026-07-03

### Changed

- **The app no longer needs a Postgres superuser — and there is no superadmin.** Fresh docker-compose installs create a least-privilege `app_provisioner` role (migrations + guild provisioning only) at first database init — in superuser context, where Postgres 15/16's privilege model requires role bootstrap to live — and point `DATABASE_URL` at it from the start. Existing deployments run `backend/scripts/create-provisioner.sql` once and switch `DATABASE_URL`; staying on a superuser keeps working but logs a boot warning. The internal superadmin flag is gone: the system database role follows PostgreSQL's standard trusted-batch model (bounded by explicit per-table grants — new tables give it nothing by default), background jobs and maintenance sweeps route into each guild under that guild's own scoped role, and the request-path role holds only the minimal shared-table access the sign-in and account-security flows use. The whole posture (role attributes, per-table access, row security) is verified by automated tests on every CI run. `FIRST_SUPERUSER_*` settings are renamed `FIRST_OWNER_*` (old names still accepted).
- **Per-request database context is now transaction-scoped.** The assumed role and tenancy variables die with each transaction and are re-applied automatically at the start of the next one, eliminating the stale-context-on-pooled-connection bug class and making transaction-mode connection poolers (PgBouncer ≥ 1.21) safe in front of the app — backend CI now runs the whole suite through one to keep it that way. Authorization snapshots held past a freshness bound now fail closed instead of executing on revoked access.
- **Database migration history squashed to a v0.53.5 baseline.** Fresh installs build the shared schema from a single baseline plus a `guild_template` schema, and never create the legacy public copies of guild content (tasks, projects, documents, …) — guild data lives only in per-guild schemas; existing deployments keep their frozen legacy copies untouched. Platform endpoints (`/users/me`, login/registration, platform admin) no longer read guild content — `initiative_roles` is populated only by guild-scoped endpoints. Guild-schema migrations are now autogenerated against a live template (`scripts/gen_guild_migration.py`) instead of hand-written, removing a class of drift.
- Faster boots on large installs: guild schemas already built by the current version are skipped by the startup sweep (set `FORCE_GUILD_BACKFILL=true` for a one-off full sweep).
- **Upgrade note:** deployments running a version older than **v0.53.2** must upgrade to any v0.53.x release and boot it once before upgrading to this version. The app refuses to start (with instructions) if the database is older.

### Removed

- Support for in-place upgrades from versions older than v0.30.0 (the `upgrade-to-baseline.sql` helper is gone; it remains available in older release tags). Upgrades from v0.30.0+ still step through a v0.53.x release as before.
- The one-time schema-per-guild startup data conversion (every deployment that can cross the v0.53.x floor has already converted).

## [0.53.5] - 2026-07-01

### Added

- **Bulk-edit access on projects, queues, counter groups, and calendar events.** Like documents, these now have a **Select** mode: pick several items, then **Edit access** to share them with people, roles, or all initiative members — in one step. The same tabbed dialog everywhere (People / Roles / All members, Viewer/Editor), and it only touches items you own or can edit. For calendar events, Select lives in the calendar's **list** view.

### Fixed

- **Documents shared with "all initiative members" now show on the project they're attached to.** The project view filtered attached documents with its own check that only understood per-person and per-role sharing, so a document shared with everyone in the initiative disappeared for members without a personal grant. It now defers to the standard document access rules (which also covers guild admins and Full-access roles).
- Chester toasts no longer overlay the bottom navigation pill and are limited to showing 2 at a time.

## [0.53.4] - 2026-06-27

### Added

- **Floating pill bottom navigation.** On phones the top toolbar (menu, search, recents) is replaced by a floating pill at the bottom of the screen with menu (showing your unread-notification count), search, and home buttons. A separate **add** button — shown on every screen size — opens the right "create" dialog for wherever you are (new task in a project, new project in the project list, new document, queue, queue item, counter, counter group, or calendar event), and expands to Add Task / Add Document everywhere else. It hides automatically when you can't create anything in the current view, and replaces the old bottom-right add buttons.

## [0.53.3] - 2026-06-27

### Added

- **Bulk-share documents with all initiative members.** The documents' bulk **Edit access** dialog has a new **All members** tab that shares — or removes sharing for — every selected document with everyone in its initiative in one step, at Viewer or Editor.

## [0.53.2] - 2026-06-27

### Added

- **Manage all of a guild's initiatives from one place.** Guild settings has a new **Initiatives** tab (admin only) listing every initiative with its member count, where you can archive, delete, or grant the Project Manager **Full access** for each one without opening each initiative individually.
- **Archive an initiative to hide it from the sidebar.** Archiving keeps everything intact (projects, documents, tasks, queues) but removes the initiative from the main sidebar for everyone; unarchive any time to bring it back. Available from the new Initiatives tab and from an initiative's **Danger zone** settings. Archiving is guild-admin only.
- **Per-guild storage limit.** A guild can now have a maximum total upload storage; uploads that would push the guild over its limit are rejected. Defaults to unlimited, so existing guilds are unaffected until a limit is set.
- **Set per-guild storage limits from the Admin dashboard.** Platform admins and owners get a new **Guilds** tab under Settings → Admin that lists every guild with its member count and current cap, where you can set (in GB) or clear each guild's maximum upload storage. Lowering a cap below current usage blocks further uploads but never deletes existing files.
- **Optional S3-compatible object storage for uploads.** Uploads can now be stored in an S3-compatible object store you point it at (a self-hosted Garage instance, AWS S3, R2, etc.) instead of the local filesystem, via `STORAGE_BACKEND=s3` and the new `S3_*` settings. The filesystem remains the default, so existing deployments are unaffected. See `docs/OBJECT_STORAGE.md`.
- **Zero-downtime migration from local to S3 storage.** A `python -m app.db.backfill_uploads_to_s3` job copies existing local uploads into the bucket (idempotent, content-type preserved, integrity-verified), and a new `S3_LOCAL_FALLBACK` setting serves any not-yet-copied blob from local disk during the cutover — so flipping a deployment with existing uploads onto S3 never drops a file. See `docs/OBJECT_STORAGE.md`.
- **Configure object storage from the UI.** Platform owners get a new **Storage** tab under Settings → Platform to choose the backend and enter all S3 settings at runtime (no env vars or restart needed), with a **Test connection** button and a **Backfill** button that runs the local→S3 migration. Saved settings override the environment variables, and the secret access key is stored encrypted and never returned to the browser.

### Fixed

- **Deleting a guild now also removes its uploaded files.** Previously a deleted guild's stored blobs were left orphaned on disk (or in the object store); guild deletion now sweeps the guild's storage namespace. Local uploads are also organized into per-guild folders (`uploads/guild_<id>/`), with any existing files relocated automatically on startup — no action needed.

## [0.53.1] - 2026-06-24

### Fixed

- Bug fix on updating permissions

## [0.53.0] - 2026-06-23

### Security

- **Permanent deletion (purge) is now admin-only at the database, not just in app code.** Emptying an item from the trash for good was gated only by an app-layer check; a `RESTRICTIVE` row-level-security policy now backs it on every soft-deletable item.
- **Changing your password now requires your current password.** This stops a leaked session token or API key from silently taking over an account by setting a new password. (Accounts that sign in only through your identity provider have no local password and are unaffected.)
- **A password change or reset now also revokes your API keys.** Previously, resetting a compromised account's password left any outstanding API keys working; a credential reset now deactivates them too, so a leaked key can't survive the response.

### Added

- **Full access for the Project Manager role.** Guild admins can now grant the Project Manager role **Full access** from an initiative's Roles settings. Members with that role can view and edit every item in the initiative — projects, documents, queues, counters, calendar events — even when an item isn't shared with them, and can manage who else has access. It applies only within that one initiative, and shows on each item's Share control as a locked editor that can't be removed. Only guild admins can turn it on, and only on the Project Manager role (so a manager can't grant it to themselves).
- **Scoped API keys (read-only and single-guild).** When creating an API key you can now mark it **read-only** (it can read but never write) and/or pin it to a **single guild** (it can only reach that guild's data). Recommended for machine credentials such as CI or an automation/MCP tool, so a leaked key has a limited blast radius. Existing keys keep full access.
- **Optional MCP server for AI assistants.** A new opt-in endpoint lets MCP-compatible AI tools (such as Claude Code) work with Initiative on your behalf — read your projects, tasks, and initiatives, and make a few safe edits (create a task, move a task, add a comment) — authenticated with your personal API key. It's **off by default** and enabled per deployment (`ENABLE_MCP`); every action runs as you, under the same permissions and access rules as the app, and a read-only API key can't make changes.

### Fixed

- Adding an option to a select / multi-select custom property lost input focus after each keystroke, so only one character could be typed at a time. Option rows are no longer re-keyed by the value being edited.
- Guild admins were wrongly shown "access denied" when opening (or saving edits to) a document they hadn't been explicitly shared on. The realtime collaboration connection didn't apply the guild-admin access bypass the rest of the app uses; guild admins now have full access to every document in their guild.

### Changed

- Sharing for projects, documents, queues, counters, and calendar events is now a single Google-Docs-style **Share** control — pick **All initiative members** (Viewer or Editor) or **Restricted** (specific people and roles), available from each item's settings and its create dialog. Replaces the separate role- and user-permission panels.
- Creating a custom-property option now asks only for a label; the stored option value is derived from the label automatically (and de-duplicated), removing the redundant Value field from the editor.
- The date picker now accepts a typed date — a text field at the top of the popover parses common formats (e.g. `2026-06-16`, `06/16/2026`, `Jun 16, 2026`) on Enter or blur — and exposes month/year dropdowns in the calendar header for quickly jumping across years instead of clicking month-by-month.

## [0.52.0] - 2026-06-16

### Security

- **⚠️ BREAKING: initiative content is now members-only, enforced by the database.** If you're in a guild but not a member of one of its initiatives, that initiative's projects, tasks, documents, and other content are now hidden from you (previously they were blocked but still visible as "exists"). This database change cannot be rolled back.
- **Initiative isolation now covers the last few gaps.** Some related data — project/document sharing and links, project tags, and per-user state like favorites, recent history, and reminders — was still reachable by guild members outside the initiative; it's now members-only like everything else. New initiative tables are required to carry these database rules going forward, so the gap can't reopen.
- **Platform-role RLS hardening (Phase 2).** The purely-platform tables (`users`, `access_grants`, `app_settings`) now enforce least-privilege at the database via per-tier `platform_<role>` policies instead of relying on the app layer alone: a member sees only their own user row, support+ can read all users, moderator+ can manage them, and app-wide config (`app_settings`: OIDC, SMTP, branding, platform AI) is owner-only to write

### Added

- **Rename built-in initiative roles.** The built-in "Project manager" and "Member" roles can now be renamed per initiative (e.g. "Project manager" → "Dungeon Master") from the initiative's Roles settings tab. The chosen name shows up wherever that member's role appears — rosters, badges, and the initiative list.
- **Configurable recent-items tab bar.** A new "Recent items in tab bar" setting (Profile → Interface) controls how many recently-opened items the header tab bar keeps and shows, from 1 to 100 (default 20). Right-clicking a tab now opens a context menu with Close, Close others, and Close all.

### Changed

- **Per-resource access grants are now a single table.** Direct access grants for projects, documents, queues, and counter groups were stored in eight separate per-resource permission tables; they are now one polymorphic `resource_grants` table resolved through a single centralized authorization path, which also brings calendar events under the same model. Existing grants migrate automatically on upgrade; pre-existing calendar events are seeded with default grants (the creator owns it, managers can edit, everyone else can view) so they stay visible to members. This database change cannot be rolled back.
- The platform users CSV export (`/admin/users/export.csv`) no longer includes the `initiative_roles` column. Initiative roles are guild-scoped; a platform-level user export now contains platform data only.

### Fixed

- **Guild admins and break-glass grant-holders now have default read/write access to all initiative content.** An admin (or an active PAM/break-glass grant) who wasn't explicitly listed on a project, document, queue, counter, or calendar event could see "no results" for that content even though their role grants full access. Access is now resolved the same way for every content type, so the admin/break-glass override applies uniformly instead of per-endpoint.
- OIDC claim mappings with the "initiative" target type showed an empty initiative dropdown after picking a guild, and saving such a mapping failed. The admin settings endpoint looked for initiatives and roles in the shared schema, where they don't live, instead of inside each guild's own schema; it now routes into every guild to list them, and the role dropdown is correctly scoped to the selected guild.
- Container failing to start on Synology NAS (and other runtimes that re-apply a stale `PATH` on image upgrade) with `start.sh: exec: uvicorn: not found`. The startup scripts now put the bundled virtualenv on `PATH` explicitly instead of relying on the image's `ENV PATH`.
- `adduser`/`addgroup` warning and failure for the default `PUID`/`PGID` of `1000` (`uid 1000 is greater than SYS_UID_MAX 999`); the container user is no longer created in the system-account range.

### Removed

- **Platform-wide role labels.** The branding setting that renamed "Admin", "Project manager", and "Member" app-wide has been removed in favour of per-initiative role names (above), which offer finer-grained control. The `app_settings.role_labels` column and the `GET`/`PUT /settings/roles` endpoints are gone.

## [0.51.1] - 2026-06-15

### Fixed

- Uploaded media (document files, featured images, and embedded rich-text images) that existed before v0.51.0 now resolves again. The v0.51.0 URL rewrite to `/uploads/{guild_id}/{filename}` ran before the per-guild schemas were created on first boot, so it migrated nothing and the old prefix-less URLs were copied into the guild schemas as-is (and 404'd). A new migration re-applies the rewrite in both `public` (per row) and every guild schema.
- Embedded PDFs now render. The PDF.js worker is bundled and served same-origin instead of loaded from a CDN, so the app's `script-src 'self'` Content-Security-Policy no longer blocks it (and it works offline in the native app).

## [0.51.0] - 2026-06-15

### Added

- **`SECRET_KEY` rotation.** `SECRET_KEY` encrypts stored data (emails, OIDC/SMTP/AI secrets) and roots the email-lookup hash, so it can't be swapped in place — a bare change would lock out every user and orphan those secrets. To rotate it, set `PREVIOUS_SECRET_KEY` to the old value, set `SECRET_KEY` to a new one, and redeploy: the app re-encrypts everything on startup (idempotent), or run `python -m app.db.secret_key_rotation` manually. Unset `PREVIOUS_SECRET_KEY` once the logs report 0 failures. A failed `SECRET_KEY` validation now spells out this path in the error.
- **`JWT_SIGNING_KEY` for independent session-token rotation.** Optional dedicated key for signing session/login JWTs; when set it decouples token signing from `SECRET_KEY`, so it can be rotated freely — the only effect is logging everyone out, with no impact on encrypted-at-rest data. Falls back to `SECRET_KEY` when unset, so existing deployments are unaffected.
- Expandable guild sidebar — the guild rail opens into a flyout showing each guild's full name and member count.
- German (Deutsch) interface language.
- Guild schemas are re-checked on every boot, so upgrades automatically add new tables to existing guilds.

### Changed

- **⚠️ BREAKING: cross-guild ("my") data moved to a new `/api/v1/me/*` API.** The personal views (My Tasks, Created Tasks, My Projects, My Documents, My Calendar, and user stats) are now served by dedicated `/me/*` endpoints, replacing the old `?scope=global`, `/projects/global`, `/calendar-events/global`, and `/users/me/stats` routes. **The personal calendar (iCal) export URL changed** from `/api/v1/calendar-events/global/export.ics` to `/api/v1/me/calendar-events/export.ics` — any subscribed calendar feeds or bookmarks pointing at the old URL must be updated. Direct API integrations calling the old routes must move to `/me/*`.
- **⚠️ BREAKING: guild-scoped API moved under `/api/v1/g/{guild_id}/*`.** Every guild-scoped endpoint — projects, tasks, documents, initiatives, queues, counters, tags, comments, attachments, imports, calendar events, task statuses, trash, and guild member management — now takes the guild in the URL path instead of resolving it from a single server-held "active guild". This lets separate tabs/windows operate in different guilds at once. The legacy `?scope=global` / `?guild_id=` query addressing and the `X-Resolved-Guild` echo header are removed; direct API integrations must move to the `/g/{guild_id}/…` paths (cross-guild "my" views stay at `/api/v1/me/*`).
- **⚠️ BREAKING: trash is split into a personal and a guild view.** Your own deleted items are now a cross-guild list at `/api/v1/me/trash` (the personal Trash page), while the all-of-guild view at `/api/v1/g/{guild_id}/trash/` is guild-admin only (no more `?scope=mine|guild`). Restore and purge are addressed per item by its owning guild.
- **⚠️ BREAKING: uploaded media is now served at `/uploads/{guild_id}/{filename}`.** Document files and embedded/featured images carry their guild in the URL so they render correctly on cross-guild pages (e.g. My Documents shows files from several guilds at once). Existing stored URLs are migrated automatically (`20260613_0103`); any hard-coded `/uploads/{filename}` links or external bookmarks must add the guild segment. Realtime sockets (events, queues, counters, collaboration) and document downloads likewise take the guild from the `/g/{guild_id}/…` path. User avatars and guild branding are unaffected (stored inline / as external URLs, never under `/uploads/`).
- **Each browser tab now holds its own guild, taken from the URL.** You can keep two tabs open in two different guilds at once — they no longer fight over a single shared "active guild". The server-held `active_guild_id` (and its `PUT /users/me/guild-context` endpoint) is removed entirely; downloads, embedded media, and live connections all resolve their guild from the page URL. The recent-items tabs bar still spans every guild you belong to.
- Notification emails and push messages are now sent in your language.
- The mobile sidebar follows your finger when swiping it open or closed.
- The assignee selector is now a searchable dropdown with checkboxes and avatar chips, matching the tag picker.
- Slim, styled scrollbars in the sidebars and on the kanban board.
- Transactional emails are easier to read: names and key details are bolded, and styling survives Gmail mobile.
- Guild admins now have complete read/write access to every initiative's projects, documents, tasks, and comments in their guild, regardless of initiative membership or per-item permissions. In initiative member settings they appear in a collapsed "Guild admins" group (greyed out, can't be removed) and can be promoted to project manager, but are never assigned a standard member or custom role.

### Fixed

- Guild admins can again create and manage projects and documents in initiatives they don't explicitly belong to (such as a guild's default initiative) — the create and visibility checks now honor guild-admin access instead of requiring a per-initiative role.
- My Tasks and Tasks I Created now sort correctly across guilds — tasks from every guild are merged and globally re-sorted by date window (Overdue, Today, This Week, This Month, Later) and due date, instead of being grouped guild-by-guild.
- A batch of schema-per-guild fixes: property definitions, uploads and document downloads, account deletion/deactivation cleanup, OIDC role sync, cross-guild calendars, and the "added to initiative" notification all read and write the correct guild's data again.
- The Initiative logo now displays in emails.
- Corrected malformed stored defaults for tag and task-status colors and icons.
- Spell-check dictionaries, Excalidraw whiteboard fonts, and the Swagger API docs page are no longer blocked by the Content-Security-Policy.
- Opening the user or theme menu from the sidebar footer on mobile no longer collapses the sidebar.

### Security

- Restored initiative-level access checks lost in the schema-per-guild cutover — leftover permission rows no longer grant access after someone is removed from an initiative.
- Email-bound guild invites can only be redeemed by the matching email address.
- HTTPS deployments now send HSTS; API docs can be disabled in production (`ENABLE_API_DOCS`); SMTP test errors no longer leak mail server details.
- Rate limiting now covers every route, and "return all rows" list requests are capped.
- Device, email-verification, and password-reset tokens are hashed at rest; device tokens now expire after 90 days of inactivity.
- Text fields are no longer HTML-encoded on save ("Foo & Bar" stays as typed) and are length-capped.
- CORS no longer reflects arbitrary origins, and a Content-Security-Policy is sent on every response.
- Validation errors no longer echo the submitted value (such as a password).
- Links in documents are restricted to safe protocols, so a stored `javascript:` link renders inert.
- Emails escape user-supplied names, so a display name can't inject a live link.
- `SECRET_KEY` is validated at startup (no placeholders, minimum 32 characters).
- CSV exports are protected against spreadsheet formula injection.
- Real-time updates only deliver events for the guild you're connected to, and logging out or resetting a password closes websocket sessions and other logins too.
- Upload hardening: size limits enforced while reading, 404 for files with no database record, short-lived scoped media tokens on native, and a cap on avatar size.
- OIDC logins require a verified email before linking to an existing account, and guild admins can no longer assign platform roles when creating users.

## [0.50.2] - 2026-06-08

### Added

- **Events can span multiple days.** A timed event's end can now fall on a later day (the 24-hour limit is gone). The create dialog and edit page gained separate end-date pickers, and the calendar draws a multi-day timed event across each day it touches — in week and day views it fills the time grid on every day (start day from its start time, full middle days, end day up to its end time) rather than sitting in the all-day bar.
- **Edit an event's tags.** The event settings page now has a tag picker (matching tasks and documents) to add or remove tags; changes save immediately.

### Changed

- **Event reminder and invitation times now show in your timezone.** Event notification emails and push messages (invitations, reschedules, cancellations, and reminders) previously printed the start time in UTC. They now render in the recipient's own timezone in a more readable form (e.g. "Wed, Jul 1, 2026 at 2:30 PM PDT").
- **Creating an event adds you as an attendee by default.** The event creation dialog now starts with you in the attendee list (you can still remove yourself).
- **Changing an event's start time keeps its length.** Adjusting the start time shifts the end by the same amount, preserving the event's duration (including multi-day spans) instead of forcing it back to one hour.
- **Consistent date, time, and color pickers for events.** The event edit page now uses the same calendar date pickers, half-hour time selectors, and color picker as the create dialog.
- **Declined attendees stop getting event notifications.** If you decline an event's invitation, you no longer receive its reschedule, update, or cancellation notifications — matching reminders, which already skipped declined RSVPs.

## [0.50.1] - 2026-06-08

### Fixed

- **Mobile app "Reload now" no longer hangs on the splash screen.** After the splash-covered OTA reload landed, tapping "Reload now" showed the splash for ~60 seconds and then re-displayed the same "New Version Available" dialog without applying the update. The reload waited for the downloaded bundle to report a `success` status that Capacitor only assigns *after* a bundle boots and confirms itself — a freshly downloaded bundle is `pending` — so the wait always timed out. The update now applies as soon as the bundle is downloaded and ready.

## [0.50.0] - 2026-06-08

### Added

- **Drag and drop to reschedule on the calendar.** On both the initiative and project calendars, drag an event or task to a different day in month view (its time of day is kept), or onto a specific day-and-time slot in week view, or to a different hour in day view — rescheduling it without opening it. A plain click still opens the item.
- **"Add Event" button on an initiative's calendar.** A floating Add Event button (matching the existing Add Task button) now appears on an initiative's Events page for members who can create events.
- **Tags on the calendar list view.** Tasks and events in the calendar list now show their tags.
- **Event notifications for attendees.** You now get a notification (bell, plus email/push if enabled) when you're invited to an event, when an event you're attending is updated or rescheduled, and when one is cancelled. Organizers are notified when an attendee responds to their invitation. A new "Events" category in notification settings controls the email and mobile channels.
- **Event reminders.** A new "Event reminders" notification category sends a reminder before events you're attending begin, with a configurable lead time (at the time of the event, 5/10/15/30 minutes, 1 hour, or 1 day before — defaulting to 15 minutes).
- **My Calendar tasks toggle.** The My Calendar view gained a Tasks toggle (matching the initiative calendar) to show or hide tasks, and a My Calendar entry was added to the command center.

### Changed

- **The chosen calendar view now persists.** Switching between day, week, month, year, or list view is remembered across sessions and devices, and shared across the Events, My Tasks, and Created Tasks calendars.
- **Tasks clearly distinguish start from due on the calendar.** Start and due dates are labeled "Start"/"Due" with distinct markers, and a task that both starts and is due on the same day now renders as a single block spanning its time slot instead of two all-day entries.

## [0.49.9] - 2026-06-06

### Added

- **Pride month mode. HAPPY PRIDE!** The Initiative logo becomes an animated rainbow gradient — a flowing, softly glowing mark that appears everywhere the logo does (sidebar, sign-in, registration, landing). The "initiative" wordmark flows the same rainbow, and primary buttons gain an animated rainbow outline (their fill and label stay solid for readability). It turns on automatically during June (Pride Month) and can be set to always On, always Off, or Auto from the appearance menu (the sun/moon toggle). The animation respects the system "reduce motion" setting.

### Fixed

- **Native app: in-app updates now apply reliably instead of re-prompting.** When the app downloaded a new version and you tapped "Reload Now," the reload sometimes failed to take and the update dialog reappeared. The app now shows a splash screen that covers the entire reload — waiting for the new version to finish downloading and verifying before swapping it in — so the update applies the first time. (Reaches existing installs after a store/APK update.)

## [0.49.8] - 2026-06-05

### Added

- **Formula bar above the spreadsheet grid.** A name box (left) shows the active cell or selected range — type a reference like `B12` or `A1:C3` and press Enter to jump there — and an editable formula bar (right) shows and edits the active cell's underlying formula or value, so you can see a formula even though the cell displays its computed result. Editing works from either the bar or the cell, and clicking cells to insert references (point mode) works while editing in the bar. The cell/range indicator that used to live in the formatting toolbar now lives in the name box.

### Fixed

- **Dragging the spreadsheet fill handle on decimals no longer produces values like `0.30000000000000004`.** Numeric fills now round each generated value to the decimal precision of the source cells (so `0.1`, `0.2` fills to `0.3`, `0.4`, `0.5`, …), eliminating the floating-point drift that previously surfaced in the filled cells.

## [0.49.7] - 2026-06-05

### Added

- **Formula reference highlights and click-to-insert in spreadsheets.** While editing a cell formula (one starting with `=`), each cell or range it references is outlined on the grid in a distinct color, and the matching reference text in the cell is colored to match. Click another cell to drop its reference into the formula, drag or shift-click to insert a range (`A1:B3`), and click again to move the just-inserted reference — so you can build formulas by pointing instead of typing.

## [0.49.6] - 2026-06-05

### Fixed

- **Add Project from an Initiative's Projects tab now always creates the project in that initiative.** Previously the new-project dialog showed the initiative you were viewing, but — when the initiatives list was already cached — could create the project in a different initiative.
- **The active-guild indicator pill shows again in the guild sidebar on home pages.** A corrupted CSS class (spaces replaced by special characters) had made the highlight invisible.

## [0.49.5] - 2026-06-04

### Added

- **Drag the fill handle to fill cells in spreadsheets.** Grab the small square on the bottom-right corner of a cell or selection and drag down, up, left, or right to fill the range. Formulas adjust their relative references as they go (`=A1` filled down becomes `=A2`, `=A3`, …) while `$`-anchored parts stay put; numeric runs and `text + number` patterns extrapolate as a series (1, 2 → 3, 4, 5; `Item 1` → `Item 2`); anything else is copied. Double-click the handle to auto-fill down to the extent of the neighboring column's data. The whole fill is a single undo step and syncs to collaborators.

## [0.49.4] - 2026-06-04

### Fixed

- **Type straight into the next spreadsheet cell after Enter/Tab.** Committing a cell edit with Enter or Tab kept keyboard focus on the grid, so you can immediately start typing into the newly selected cell instead of having to click it first.

## [0.49.3] - 2026-06-04

### Added

- **Formulas in spreadsheet cells.** Start a cell with `=` to write a formula — arithmetic (`=A1+B1*2`, `=(A1+A2)/2`, percentages, exponents) plus common functions like `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `IF`, `ROUND`, and `ABS` over single cells or ranges (`=SUM(A1:A10)`). Cells show the computed result and recalculate live as their inputs change, including edits from collaborators; number formats (currency, percent, etc.) apply to results, and errors such as `#DIV/0!` or a circular reference (`#CYCLE!`) show in red with a tooltip. Inserting or deleting rows/columns rewrites references so formulas keep pointing at the right cells, and copying or exporting to CSV/XLSX emits the computed values.
- **Cut and move cells in spreadsheets.** Press Ctrl/Cmd+X to cut a cell or range — the source gets a dashed marquee and is left untouched until you paste, at which point the cells (formulas and all) move to the new location. Press Escape, copy, or start editing to cancel the cut.
- **Insert and delete spreadsheet rows and columns.** Right-click a row or column header in a spreadsheet document to insert a line before or after (above/below for rows, left/right for columns), or delete the selected line(s). The "Insert multiple…" submenu takes a count so you can add several rows or columns at once. Existing cells, styles, number formats, and frozen panes all shift to stay aligned, and selecting a band of headers first lets you insert next to — or delete — the whole range at once.

## [0.49.2] - 2026-06-03

### Added

- **Sort a spreadsheet by a column.** Right-click any column header in a spreadsheet document and choose "Sort A → Z" or "Sort Z → A" to reorder the whole sheet by that column, keeping every row's other cells (and their formatting) aligned. Blanks always sort to the bottom, and frozen header rows stay pinned in place.

## [0.49.1] - 2026-06-01

### Added

- **Shift+click range selection in data tables.** In selection mode you can now click one row's checkbox, then shift+click another to select every row in between (inclusive) in the order they're displayed.

### Fixed

- **Data table selection no longer desyncs when filtering.** Rows you select stay selected when you filter them out of view and then clear the filter — the checked boxes always match the selection used for bulk actions. The selection count also reads sensibly when a filter hides some of your selected rows (e.g. "5 selected (2 match filter)").

## [0.49.0] - 2026-06-01

### Added

- **Self-hosted over-the-air (OTA) app updates.** The native mobile app now downloads the web bundle that matches the backend it's connected to, so the frontend and backend stay in sync without reinstalling the APK for every release — no paid live-update service required. Each server build ships the matching Capacitor bundle; on launch and when returning to the foreground the app checks the server version and, if it differs, downloads the bundle and prompts "Reload now" (with a "Later" option). A failed update automatically rolls back to the previous bundle. When a release changes native code (not just web assets), the app detects that its installed shell is too old and asks you to update from the store/APK instead. Releases that only change web assets no longer rebuild the APK — they update entirely over the air.

## [0.48.1] - 2026-05-31

### Fixed

- Kanban drag-and-drop is more reliable: dragging a card to the top of a column no longer snaps it to the second slot.

## [0.48.0] - 2026-05-31

### Added

- **Graduated platform roles.** The two platform-level roles (`admin`/`member`) are replaced by a five-rung ladder — `member` → `support` → `moderator` → `admin` → `owner` — backed by a capability model so each platform operation is gated on the specific privilege it needs instead of a single all-or-nothing "admin" flag. App-wide configuration (OIDC, SMTP, branding, role labels, platform AI) now requires the `owner` role; user management, guild management, and role assignment are split across `moderator`/`admin`. Role assignment is bounded (you can't grant a role above your own), and the platform can never be left without an `owner`. Existing platform admins are automatically promoted to `owner` so no one loses access. The old single admin page is now split into two capability-gated areas: **Platform settings** (`/settings/platform` — auth, branding, email, AI; owner-only) and an **Admin dashboard** (`/settings/admin` — users and access; for support/moderator/admin), surfaced as separate entries in the sidebar menu and command palette.
- **Privileged Access Management (time-bound guild access).** Lower-privilege platform users (e.g. `support`) can now request temporary, per-guild access instead of relying on a standing all-guild bypass. A request specifies the guild, a read-only or read-write level, a duration, and a reason; an `owner`/`admin` approves, denies, or revokes it, and it auto-expires. Maximum duration is tiered by role for least privilege — `support` ≤ 4h, `moderator` ≤ 8h, `admin` ≤ 24h — enforced server-side and reflected as the preset options offered in the request form. Within the granted guild a grant acts like a time-boxed, read-only-or-read-write member: it reaches every initiative, project, document, queue, and counter group (consistently at both the RLS layer and the app-layer permission checks, so what a grantee can list they can also open). Grants are scoped at the database level (PostgreSQL RLS) to the one granted guild — read grants cannot write, owner-only operations stay blocked, and no grant can touch guild memberships, settings, or other identity/config tables, so a grant can never be used to escalate to guild admin. Requesters and approvers are notified in-app, by email, and via mobile push (when SMTP / FCM are configured) — each linking to the **Admin dashboard → Access** tab, which houses the request form and approval queue. Once a grant is live, the granted guild appears in the sidebar switcher marked as temporary (with a remaining-time tooltip); entering it shows a read-only banner and hides write affordances, and it disappears when the grant expires.

### Changed

- **Task reordering is now incremental and precise.** Dragging a task to reorder it sends only the moved task with a fractional "midpoint" position instead of renumbering and re-sending the entire list, so reorders are faster and no longer bump the `updated_at` of tasks that didn't move. Task order is stored at higher precision (NUMERIC) to allow many in-between insertions, with an automatic server-side rebalance when a gap is exhausted — matching how counters and queue items already order.

### Fixed

- Fixed two kanban drag-and-drop bugs in the project task board: you couldn't drag a card below the one directly beneath it (it snapped back), and you couldn't drop a card into the first slot of another column (it landed in the second). Drop placement now follows where the card is actually released — which half of the target card it overlaps — instead of inferring direction from list position, so every slot is reachable. List/table reordering was unaffected.

## [0.47.0] - 2026-05-29

### Added

- **Password complexity requirements.** New passwords must be at least 12 characters and are checked against the HaveIBeenPwned breach corpus via the k-anonymity API (only a 5-char SHA-1 prefix leaves the server). Enforced on registration, password reset, self password change, and admin user creation/update; no character-class rules per NIST SP 800-63B guidance. Existing accounts are grandfathered — short or breached passwords keep working at login until the next change. Disable the breach check by setting `HIBP_CHECK_ENABLED=false` in the backend env (e.g. for air-gapped deployments).
- **Task edit page shows who created the task and when.** A small avatar + "Created by {name} · {relative time}" chip sits inline with the task title (right-aligned, out of the way of the edit form). Hovering reveals the absolute creation timestamp. Follows the existing avatar conventions (deterministic colour fallback, anonymized-user handling, `User #<id>` fallback when the creator is no longer in the guild).
- Manual save button on document titles.
- **Version history for uploaded file documents.** Uploaded files (PDFs, Office docs, images) now keep a version history instead of being a single replaceable blob. A "Version history" popover on the file viewer lists every version (newest first) with its upload time; selecting an older version views or downloads it, and an inline trash button on each row deletes it. Anyone with write access can upload a new version (it must match the original file type); only the document owner can delete versions. Deleting the current version rolls back to the previous one; the last remaining version can't be deleted (delete the document instead). Old version blobs are cleaned up when the document is purged.

### Changed

- **Guild deletion is harder to trigger by accident.** The delete control moved off the first guild-settings tab into its own dedicated "Danger zone" tab, which now spells out exactly what deletion removes (initiatives, projects, tasks, documents, members, invites, and settings). Confirming requires typing `DELETE GUILD <NAME>` (the whole phrase uppercased) and re-entering your password; OIDC-only accounts, which have no password, are asked only for the phrase.
- **Active Guild highlight.** The active guild is now highlighted by a more subtle bottom pill when on a home page (My Tasks, My Documents, etc), to reduce confusion on where you are in the app.

## [0.46.2] - 2026-05-27

### Added

- **Counter `+`/`−` button feedback.** Each press fires a short audio tick (`tick.wav` on increment, `tick_reverse.wav` on decrement) and a brief haptic tap. Works on both the row/grid cards and the focus view. No user preference gating yet.

### Changed

- **Counter `+`/`−` buttons disable at their bounds.** When a counter is at its configured `max`, the `+` button is disabled; at `min`, the `−` button is disabled. Applies to both the row/grid cards and the focus view. Counters without a configured bound (`null` min/max) are unaffected.
- **Counter `+`/`−` buttons tap more reliably on mobile.** Added `touch-action: manipulation` to the step buttons so a slight finger wobble during a press no longer cancels the click as a swipe, and the synthetic-click delay is gone.
- Removed email from the app sidebar to protect user privacy.

## [0.46.1] - 2026-05-24

### Added

- **Counter focus view.** Each counter can now be opened in a full-screen, mobile-first layout via the "Open full screen" menu item on the row (URL: `/g/{guildId}/counter-groups/{groupId}/counter/{counterId}`). The view scales the value, progress bar, or segmented-clock dial to fill the viewport, exposes thumb-zone-sized `−`/`+` controls in the bottom safe area, lets you cycle through the group's counters with chevrons or a horizontal swipe, and stays in sync with other clients via the existing WebSocket. Counter view components gained a `2xl` size variant used by this layout.

### Changed

- **Filter and view-mode preferences are now per-user, not per-device.** Project task filters (assignee, tag, status, due, property, show-archived, view mode), the Projects / Documents / My Tasks / Created Tasks / My Documents / My Projects / My Calendar filter sets and sort orders, and the counter group row/grid layout toggle now persist to a new `user_view_preferences` table keyed by `(user_id, scope_key)` instead of `localStorage`. Set filters once and they apply on every device you sign in to. A one-shot migration on first authenticated load uploads any legacy `localStorage` values to the server and clears them locally. Sidebar collapse states, side-panel state, and similar device-specific UI prefs still live in local storage.

## [0.46.0] - 2026-05-23

### Added

- **Recent items bar now spans more than projects.** The sticky tabs strip at the top of the app surfaces the 20 most recently opened guild-scoped items across projects, documents, queues, and counter groups, ordered by last viewed. Each tab shows an entity-specific icon (project emoji, file-type icon for documents, `GalleryHorizontalEnd` for queues, `Gauge` for counter groups) and links to the matching detail page. The previous projects-only `/projects/recent` endpoint has been replaced by a polymorphic `recent_views` table and a single `GET /api/v1/recents` endpoint; new `POST /<entity>/{id}/view` and `DELETE /<entity>/{id}/view` endpoints record/clear views for each of the four entity types.
- **Command center expanded.** The Suggested group now lists the top 5 mixed recents (projects, documents, queues, counter groups) instead of projects only, and dedicated Queues and Counter Groups sections were added so they participate in fuzzy search the same way Projects and Documents do. The Tasks group defaults to the 25 most recently updated tasks assigned to you (skipping done) — so you see what you're actively working on instead of the top of every project's kanban. The Documents group likewise defaults to the 25 most recently updated documents in the active guild. Typing in the input now performs a guild-wide title search against the backend for both tasks and documents, so any item is reachable from the command center regardless of whether it's in the default list.
- **Global "Add Document" action.** Mirroring the existing global Add Task wizard, a new guild-then-initiative picker is reachable from the command center's Actions group and from a new "New document" button in the My Documents page header. The wizard auto-advances when there's only one guild / initiative, persists a "last used" shortcut for one-click access, and hands off to the existing Documents page (`?create=true&initiativeId=…`) so the actual creation UI is unchanged.

## [0.45.1] - 2026-05-22

### Added

- **Hold your turn (queues).** A new Hold button on the queue toolbar pauses the current turn — the held participant leaves the rotation, and Next advances to whoever's up next. Held items appear in a dedicated "Held" section above the rotation in the On Deck view, each with an "Act" button. Clicking Act opens a small menu with two options: **Act in place** keeps them at their original queue position so they re-enter at their natural slot when the rotation reaches it again, while **Act and reposition** rewrites their initiative to land just above the current turn and makes them the current turn — PF2e Delay semantics, where the new slot persists for the rest of the encounter. If they never act, the rotation auto-restores them at their natural slot the next time it comes around — so a held player can't be silently forgotten. Held state is recorded with the round the hold happened in (`held_at_round`), so the auto-release logic knows when their slot is "due back."
- **"On Deck" view for queues.** A new view mode on the queue detail page renders upcoming turns as a vertical sequence: the current turn sits at the top, the next item rises into the top slot on Next, and the previous current turn rolls down to its place in the next round behind a round separator. The separator stays anchored across turns (it morphs into position rather than popping in and out, so the round-boundary transition animates smoothly) and its label crossfades when the round number changes. Stopping the queue resorts the rows back to default (position-desc) order and clears the current-turn highlight. Animations are driven off the cached queue data, so they play uniformly for the local user's turn clicks, the matching server response, *and* WebSocket-driven refetches when another participant advances the queue — via the View Transitions API (with a graceful fallback for older browsers and `prefers-reduced-motion`). Hidden items appear below a "Hidden" divider so they remain editable from the same view without taking a turn. "On Deck" is the default view; the choice (list or on-deck) is remembered per queue.
- **Sort all counters in a group at once.** A "Sort" dropdown on the counter group toolbar reorders every counter by name (A→Z / Z→A) or current count (low→high / high→low). The sort persists by reassigning each counter's position on the backend and broadcasts over WebSocket so other viewers update live; manual drag-and-drop reordering still works afterward.
- **Duplicate a counter group.** A "Duplicate" action in the counter group settings (Advanced tab) creates a copy with all of its counters and their current values, bounds, view modes, and order. The copy keeps the source group's role and user permissions and makes you the owner; you can name the copy or accept the default "(Copy)" suffix.

### Changed

- **Queue item positions are now fractional.** `queue_items.position` is stored as `Numeric(20,10)` instead of an integer, so items sharing the same initiative value can be ordered with finer granularity (e.g. dropping an item at `10.5` between two items at `10` without renumbering them), matching the fractional-position indexing already used by Counters.
- **Queue turn controls feel instant.** Start, stop, next, previous, reset, and set-active now update the displayed current item and round optimistically instead of waiting for the API round trip, then reconcile with the server (and the queue WebSocket) once it responds. A failed request rolls the change back.

## [0.45.0] - 2026-05-22

### Added

- **Counters advanced tool for initiatives.** A new initiative-scoped feature for tracking numeric values like HP, ammo, scores, or budgets. Data model is `Initiative > Counter Group > Counter`, mirroring Queues with full DAC (user + role permissions), guild-scoped RLS, soft-delete, and real-time WebSocket updates. Each counter has its own `count`, `min`/`max` bounds, `step`, `initial_count`, and view mode (`number`, `progress_bar`, or `segmented_clock`). Counts can be set directly, incremented/decremented by step, or reset to the initial value; a "Reset All" button on the group resets every counter at once. Counters use fractional-position indexing (`Numeric(20,10)`) for single-PATCH drag-and-drop reordering within a group. Adds the `counters_enabled` initiative master switch and `counters_enabled` / `create_counters` per-role permission keys (backfilled: managers ON, members OFF). New routes: `/counter-groups`, `/counter-groups/:groupId`, `/counter-groups/:groupId/settings`.

### Fixed

- **Spreadsheet column/row resize now persists on Mac (and other high-DPI/Retina devices).** Pointer events on Retina displays report fractional coordinates (e.g. `clientX = 123.5`), which the spreadsheet's `clampInt` integer validator rejected. The sanitized formatting record then came back empty, and `updateColumn` / `updateRow` interpreted that as "delete the entry" — so releasing the mouse silently reverted the column or row to its default size. The resize handler now rounds the new size to an integer before committing. Also rewrote the resize event wiring to attach `pointermove` / `pointerup` / `pointercancel` listeners synchronously inside `pointerdown` (eliminating a latent race where a fast release on a Mac trackpad could miss `pointerup` before the React effect attached).

- **Pagination control now resyncs when external code resets the page.** When a filter change called `setPage(1)` on the My Tasks / My Projects / My Documents / Created Tasks / Documents / Tag Tasks tables, the underlying query refetched page 1 correctly but the DataTable's internal pagination control kept its old `pageIndex`, so the UI continued to show the previous page number and an empty/short data page. DataTable now accepts a controlled `pageIndex` prop in `manualPagination` mode and syncs to it on change. Bug existed since manual pagination was introduced; surfaced while validating filter behavior in the Biome migration.

### Changed

- **Frontend tooling: migrated from ESLint + Prettier to Biome.**

## [0.44.3] - 2026-05-18

### Fixed

- **iOS/Android native app: content no longer renders behind the status bar.** All viewport-level sticky headers and sidebars now absorb the safe area inset at the top, so controls appear below the status bar on devices with a Dynamic Island or notch. The fix covers the main app header, the guild icon column, both sidebar headers (home and guild views), the document side panel, and the activity sidebar. The home indicator safe area is also applied at the bottom on native iOS.
- **Native iOS app could not connect when `CORS_ALLOWED_ORIGINS` was restricted (follow-up to v0.44.2).** Capacitor's iOS WebView uses `capacitor://` as the default URL scheme, producing the origin `capacitor://com.morelitea.initiative` — distinct from the `https://` origin Android sends. This origin was not included in the automatic native-origins allowlist, so iPhones were still rejected. The backend now allows `capacitor://com.morelitea.initiative` in addition to `https://com.morelitea.initiative`. The Capacitor config also adds `iosScheme: "https"` so future iOS builds use the same `https://` origin as Android, making a single origin sufficient going forward.

## [0.44.2] - 2026-05-17

### Fixed

- **Native iOS/Android app could not connect when `CORS_ALLOWED_ORIGINS` was restricted.** Capacitor native apps send requests from `https://com.morelitea.initiative`, which was not included when operators set a specific origin allowlist. The backend now automatically appends the Capacitor native origins to any non-wildcard `CORS_ALLOWED_ORIGINS` list, so the mobile app works without requiring manual configuration.

## [0.44.1] - 2026-05-17

### Fixed

- **HTML and SVG documents now preview in the in-app viewer.** The `X-Frame-Options: DENY` header added in 0.44.0 also applied to the document-download endpoint, so the file viewer's iframe was blocked from displaying uploaded HTML/SVG files (`refused to display … X-Frame-Options to 'deny'`). The inline document response now sends `X-Frame-Options: SAMEORIGIN` and `Content-Security-Policy: frame-ancestors 'self'`, so the same-origin viewer can render them while cross-origin framing stays blocked. The existing `script-src 'none'` and sandboxed iframe are unchanged — uploaded HTML still cannot execute scripts, so there is no stored-XSS regression.

## [0.44.0] - 2026-05-16

### Added

- **Spreadsheet undo/redo (per session).** Spreadsheets now support undo/redo via toolbar buttons and keyboard shortcuts (Ctrl/Cmd+Z, Ctrl+Y / Cmd+Shift+Z), covering cell edits, paste, formatting, borders, column/row resize, freeze, and CSV/XLSX import. History is per user and per session and works whether collaboration is on or off; a peer's edits are never undone by you. Built on a new editor-agnostic `useYjsHistory` primitive (wrapping `Y.UndoManager`) that any future Yjs-backed editor can reuse with a small adapter.
- **Spreadsheet formatting and Excel import/export.** Spreadsheet documents now support column widths and row heights (drag the header edges; double-click to reset), number formats (currency, percent, date, fixed decimals, adjustable decimal places, thousands separator, and negative styles including red and parentheses), frozen header rows/columns, text/fill styling (bold, italic, underline, strikethrough, font size, text color, background fill, horizontal and vertical alignment), and per-edge cell borders (thin/medium/thick/dashed/dotted/double, any color, with all/outer/side presets). Formatting applies to the current selection — a cell range, or whole columns/rows selected from the headers — via a responsive formatting toolbar (related controls grouped into popovers on desktop, collapsed into a single overflow panel on small screens; file import/export lives in a compact menu), and syncs in real time to collaborators. A new "Export Excel" action produces a styled `.xlsx`, and the import button now accepts `.xlsx` alongside CSV, preserving widths, styles, number formats, borders, and frozen panes on round-trip (CSV import/export is unchanged). Existing spreadsheets upgrade transparently on next save (content schema v1 → v2) — no migration or operator action required.

### Security

- **Auto-sanitize HTML on all API inputs.** Every Pydantic schema now extends `SanitizedBaseModel`, which runs `nh3.clean()` on every `str` field at validation time. Dangerous markup — `<script>`, `<iframe>`, `on*` event-handler attributes, `javascript:` URLs — is stripped before reaching services or the database. Safe formatting tags (`<b>`, `<i>`, `<a>`, `<p>`) pass through unchanged, and fields that must preserve user-authored content (descriptions, comments, document content, queue notes) opt out via the explicit `RichTextStr` type. Enum-typed fields are skipped automatically.
- Limit image attachment uploads to 10 MB to prevent memory exhaustion
- Block OIDC new-account creation when `ENABLE_PUBLIC_REGISTRATION` is disabled
- Return opaque error codes from import parse endpoints instead of raw exception text
- Add 5-minute TTL to OIDC discovery metadata cache
- Add `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers to all responses
- Guard AI settings `base_url` against SSRF — validates against private/loopback/link-local IPs at both request time and write time for ollama and custom providers
- Add `CORS_ALLOWED_ORIGINS` config variable to replace the `allow_origins=["*"]` placeholder
- **Stored XSS in legacy document embed nodes.** The Lexical `EmbedNode` (kept around for backwards compatibility with documents that used the old generic embed type before `YouTubeNode` / `TweetNode` existed) rendered its stored `html` field via `dangerouslySetInnerHTML` without sanitization. A user able to write a document — i.e. any guild member with edit access — could craft a serialized JSON payload containing `{ "type": "embed", "html": "<script>…</script>" }`, save the document, and have the script run in every other viewer's session. The constructor now passes the html through DOMPurify before storing it on `__html`, so all entry paths (importJSON of legacy data, paste-conversion via `convertEmbedElement`, programmatic creation) are sanitized at the same boundary. Default DOMPurify config strips `<script>`, event handler attributes, `javascript:` URLs, and `<iframe>`; legacy YouTube embeds may render empty after the fix and should be re-added with the dedicated `YouTubeNode` insert tool.
- **Migrate password hashing from passlib[bcrypt] to argon2-cffi.** passlib's last release was Oct 2020; its bcrypt backend has been emitting `(trapped) error reading bcrypt version` ever since bcrypt 4.1 removed the `__about__` module, and the project's `bcrypt==4.0.1` pin existed only to keep passlib quiet. New password hashes are now argon2id (OWASP-aligned defaults), and existing bcrypt hashes are still verified directly through the `bcrypt` library so nobody is locked out. On the next successful login (standard form auth or device-token auth) any bcrypt hash is rewritten as argon2id transparently — no schema change, no migration, no operator action required. bcrypt itself bumps from 4.0.1 to 5.0.0 along the way, since the version pin was only there to dodge the passlib incompatibility.

### Changed

- Restrict Ollama AI provider to platform-level settings. Guild and user AI settings no longer offer Ollama as a provider option (it cannot reasonably be reached from outside the host's network anyway). A migration nulls out any pre-existing Ollama overrides on guild_settings and users, falling back to the inherited platform configuration.
- Show an inline HTTP warning on the platform AI page when the Ollama base URL is configured with `http://`, reminding admins to use TLS in production.
- Platform admins can now point Ollama / custom AI base URLs at `http://` or private addresses. The SSRF guard still applies to guild/user-supplied URLs in the test-connection and fetch-models endpoints; it is bypassed only when the caller is a platform admin (who already controls the host). AI generation paths trust ollama URLs unconditionally now that ollama is platform-only.
- Bump vite from v7 to v8. Decreases bundler step from 25s to 2s.
- Migrate to typescript 7 beta. Decreases compile step from 25s to 5s.
- Bump Dockerfile Node.js from v20 to v24.
- Pin pnpm to 10.33.3 via the `packageManager` field in `frontend/package.json`. CI and the Dockerfile auto-detect it through corepack, so contributors no longer need to match versions manually — fresh clones with corepack enabled get the right pnpm on first invocation.

## [0.43.2] - 2026-05-03

### Added

- **Optional captcha gate on registration.** Set `CAPTCHA_PROVIDER` (one of `hcaptcha`, `turnstile`, or `recaptcha` — v2 only for reCAPTCHA, since the gate uses the rendered checkbox widget rather than v3's score flow), `CAPTCHA_SITE_KEY`, and `CAPTCHA_SECRET_KEY` and the public registration endpoint will require a solved widget before creating an account. The SPA picks the right widget at runtime based on `GET /api/v1/config`. Bootstrap-first-user registrations (no users yet) and the OSS default (no env vars set) are silently skipped — registrations work exactly as before. The verifier fails closed on provider network errors, so a transient outage rejects registrations rather than letting them through unchecked.

### Changed

- **Auto-detect timezone on registration.** The register form now forwards the browser's resolved IANA timezone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) so a new account's wall clock matches where the user actually is, instead of starting at the model default of `"UTC"`. Time-of-day features (rolling recurrence, due-date display, daily digests) read the stored zone, so the new default removes a step from the "why is my task scheduled at 5 AM?" loop. Non-SPA callers (curl, integration scripts) that omit the field still get the `"UTC"` default — no breaking change. OIDC sign-in still picks `"UTC"` until the user updates it in settings; that flow has no SPA form to attach the value to.

- **Timezone editor on the Profile tab.** Settings → Profile now exposes the same timezone picker that's been on Settings → Notifications, so a wrong default surfaces and is fixable on the first profile pass instead of requiring users to find the notifications tab. The picker, fallback list, and `Intl.supportedValuesOf("timeZone")` resolution moved to a shared `lib/timezones.ts` so both pages stay in sync.

### Fixed

- **Rolling recurrence off-by-one across the UTC date boundary.** A task set to repeat "every N days after completion" anchored its next due date on the UTC calendar day, not the user's local one. For tasks whose local time crossed midnight UTC (e.g. 5pm Los Angeles is 00:00 UTC the next day), completing the task one local day earlier than the UTC day produced a next occurrence one day too soon — `every 3 days` ended up scheduling 2 days out. The advance step now converts both `now` and the original due time into the user's stored timezone before doing the date math, so the new occurrence lands on the user-intuitive calendar day.

- **Settings unreachable when you have no guild memberships.** A user with zero memberships used to see only the "no guild" screen with create/join/logout — no path to user settings (so no way to delete their own account) and no path to platform-admin settings either. The empty-state screen now exposes **Account settings** (always) and **Platform settings** (when `user.role === "admin"`) buttons, and the `/profile/*` and `/settings/admin/*` routes render in a minimal Back-to-start shell instead of bouncing back to the empty state.

## [0.43.1] - 2026-05-02

### Changed

- **Self-deactivation / deletion UX.** Settings → Danger Zone now exposes **Deactivate Account** and **Delete Account** as two separate buttons next to their descriptions, instead of a single ambiguous opener that landed on a radio chooser. Each button takes you straight to the eligibility check for that action, the dialog title and step descriptions match the action you picked, and the deactivate copy now spells out that you'll be removed from every guild you're in (rejoining requires a fresh invite).

### Fixed

- **Orphaned projects when leaving a guild.** Leaving a guild while owning projects in it would silently strand the rows: the user's initiative membership got dropped, no DAC permission survived, and guild admins (who have no implicit project bypass) couldn't reach them. Leaving now forces a per-project decision — for each project you own in the guild, the dialog asks whether to transfer ownership to a project manager or delete the project (which sends it to the guild's trash retention bucket). The transfer-recipient picker is filtered to initiative managers since they're the role that actually administers projects. The eligibility endpoint surfaces the project list so the SPA can pre-flight the prompt, and the backend rejects a leave whose disposition map doesn't cover every owned project exactly once. The OIDC group-sync removal path, which has no UI to ask, auto-transfers ownership to an active initiative manager (falling back to a guild admin) before dropping the user, and logs a warning when neither exists.

- **Orphaned projects when a guild admin removes a member.** The user-management table's "Remove from guild" button shared the same orphan hazard as self-leave: the backend just dropped initiative memberships and walked away. The remove dialog now pre-flights `GET /users/{user_id}/guild-removal-eligibility` and renders a per-project radio (transfer to a project manager, or delete) so the admin always has an escape hatch — including for projects in initiatives where no other PM is available. The eligibility response bundles candidate transfer recipients per-project, so the picker works even for initiatives the admin doesn't belong to.

- **Project access dropdown blank for a reactivated former owner.** If a project owner self-deactivated (which forced an ownership transfer to another member) and was later reactivated and re-added to the initiative, the project's individual-access list showed them at the old `level=owner` but the access dropdown was blank because two users now had owner-level rows pointing at the same project. `transfer_project_ownership` now drops the departing owner's `ProjectPermission` row as part of the transfer — every call site is a "user is leaving" path so the row was already stale.

- **Wrong password on the deactivate / delete form signed you out.** The self-deletion endpoint returned `401 UNAUTHORIZED` for a password mismatch, which the SPA's global axios interceptor treats as a session-expiry signal and force-logs-out from. The user was kicked back to the login screen instead of seeing "wrong password" inline. The endpoint now returns `400` for that specific case (the user _is_ authenticated — they just typed the wrong confirmation password), so the error stays scoped to the form.

- **Error toasts no longer leak raw backend codes.** A class of `toast.error(...)` call sites was passing through the raw `error.message` or `response.data.detail` string as a fallback, which surfaced backend constants like `USER_INVALID_PASSWORD` to users when there was no client-side mapping. All of those now route through the existing `getErrorMessage(error, "namespace:fallbackKey")` helper, which looks up the code in the `errors` translation namespace before falling through to a localized fallback. The `errors` namespace is also now preloaded with `common` so the lookup works on any page (previously, only pages whose `useTranslation` happened to include `errors` resolved codes correctly).

## [0.43.0] - 2026-05-01

### Added

- **Spreadsheet documents.** Pick **Spreadsheet** from the document-type dropdown when creating a new document to get a virtualized cell grid that scrolls horizontally and vertically without bound. Edit cells with click + type / Enter / Tab / arrow keys; copy and paste between cells (and from Numbers / Excel / Sheets — multi-row / multi-column blocks expand into the grid). Toolbar buttons export the sheet as CSV or import a CSV file. Cells store strings, numbers, booleans, or blanks; numeric- and boolean-looking inputs get auto-coerced to the right type, and booleans render as interactive checkboxes. Edits sync in real time between users on the same document over the existing yjs collaboration infrastructure, and each user's currently-selected cell shows up to peers as a colored ring with their name.

- **Webhook subscriptions for the advanced-tool service.** Outbound HMAC-signed event delivery (sha256 over `timestamp + "." + body`) so the embed can react to writes (e.g. `task.created`) without polling. Subscriptions are guild-scoped, RLS-protected, and the HMAC secret is returned only at create time. _Note: likely temporary scaffolding for testing the embed integration; expect the contract to shift as it shakes out._

- **Delegation auth for the advanced-tool service.** Accept short-lived RS256-signed JWTs from the embed's backend so it can call Initiative on a user's behalf. Existing RLS + role-permission checks still gate every action — delegation answers only "who is acting." Deactivated users can't be impersonated. Disabled by default; opt in with `AUTO_DELEGATION_PUBLIC_KEY_PEM`.

- **Embedded advanced tool integration.** Initiative now supports plugging in an externally-deployed companion app as an iframe panel under specific initiatives or as a dedicated guild settings tab. Operators set `ADVANCED_TOOL_NAME` and `ADVANCED_TOOL_URL` on the backend; without those, the entire feature stays fully hidden — no UI surface, no per-initiative toggle, and the API endpoints return 404.
  - **Per-initiative panel** — initiative managers turn it on under Initiative settings → Details → Advanced Tools. Once enabled, the panel becomes the first item in the initiative's sidebar group for any user whose role grants the new `advanced_tool_enabled` permission.
  - **Per-guild panel** — guild admins get a dedicated tab in guild settings for cross-initiative or admin-only views. The tab only appears when the deployment has an advanced tool URL configured AND the user is a guild admin.
  - **Role-based access control** — two new initiative-level permission keys (`advanced_tool_enabled`, `create_advanced_tool`) gate visibility and creation rights at the role level. Built-in managers get both by default; members get neither.
  - **Security model** — embedding uses a 60-second audience-scoped JWT delivered to the iframe via postMessage (never the URL). Strict origin checks on every postMessage; iframe is sandboxed (`allow-scripts allow-same-origin allow-forms allow-downloads`); locale forwarded so the embed picks up the user's language without re-prompting. JWT can be signed with RS256 via `HANDOFF_SIGNING_PRIVATE_KEY_PEM` so the embed verifies with a public key only — no shared secret. Falls back to HS256 with `SECRET_KEY` for OSS deployments. Tokens carry a `jti` so the embed can refuse repeat redemption within the validity window. The handoff endpoint authorizes membership + role + master-switch + URL-configured before issuing a token, so the embed never has to make access decisions on its own.
  - **Runtime config endpoint** — `GET /api/v1/config` exposes the deployment's advanced-tool config (URL + name) so the SPA discovers it at boot without rebuilding the bundle.

- **Project export & import.** Settings → Advanced now offers an **Export as JSON** button that downloads a self-contained JSON file with the project's metadata, task statuses, project tags, tasks (with subtasks, recurrence, priorities, dates, and custom property values), and the property _definitions_ those tasks reference. From the projects page, an **Import** button next to **New project** accepts a JSON export and recreates the project under any initiative you can create projects in — including across separate Initiative installations. References are name- and email-based so IDs from one database don't leak into another:
  - **Tags** are matched against the target guild by name; new tags are created if they don't exist.
  - **Task statuses** are recreated per-project from the export.
  - **Custom properties** are matched by name in the target initiative. If the target already has a property with the same name but a different type, the imported one is renamed `<name>_<type>` (e.g. `Severity_select`) so the existing property is never mutated.
  - **Assignees** are matched by email against the target initiative's members. Unmatched emails are reported in a toast warning and silently dropped — the importer becomes the project owner and `created_by` for every task.
  - The format is **versioned** (`schema_version`) so future format changes can refuse stale exports cleanly.

- **Trash and Restore.** Deleting a project, task, document, comment, initiative, tag, queue, queue item, or calendar event now sends it to a trash can instead of permanently destroying it. Items stay there for the guild's retention period (default 90 days; admins can change it under **Settings → Guild → Trash retention** or set "Never" to keep things forever).
  - **Personal view** — every member sees a **Trash** tab under their profile listing the things they deleted, with a **Restore** button next to each.
  - **Guild view** — guild admins also get a **Trash** tab under **Settings → Trash** that shows everything trashed in the guild plus an admin-only **Delete now** button for permanently purging an item before its retention timer is up.
  - **Restore handles missing owners** — if you trashed a task and the owner has since left the initiative, restore opens a picker so you can hand ownership to someone else before bringing the row back.
  - **Cascades preserved** — trashing a project hides its tasks too; restoring it brings them back together. The trash listing only shows the parent so you don't get drowned in 200 cascaded rows.
  - **Auto-purge** runs hourly so expired items leave on their own.
  - The Postgres layer now refuses raw `DELETE` from the application role on every soft-delete-capable table, so a stray query can't accidentally bypass the trash flow.

- Export users as CSV from **Settings → Users** (guild admins) and **Settings → Admin → Users** (platform admins). Each row gets an **Export** button, and the card header has **Export all as CSV**. Exports include ID, email, full name, role, status, and initiative roles — enough for HR or compliance teams to keep an offline record before an account is removed.

- **Chester the Mimic** — a pixel-art treasure chest mascot now greets you in toast notifications. Each toast type pairs with a Chester mood (success → proud sparkles, error → chomping, warning → thinking, info → talking, default → idle), and the seven mood SVGs ship as standalone animated assets. Platform admins can preview them all from the new "Chester toast playground" card in **Settings → Admin → Branding**.

- **Keep screen awake.** A new toggle under **Settings → Interface** prevents this device's screen from dimming or locking while the app is open. Useful for long planning or reading sessions on a tablet at the table. The setting is per-device — it's saved locally (localStorage on web, Capacitor Preferences on native) and never synced to the backend, so each device can opt in independently. Uses the Screen Wake Lock API on web and the native idle-timer/`FLAG_KEEP_SCREEN_ON` flag on Capacitor builds.

### Changed

- **Account deletion now has three options instead of one.**
  - **Deactivate** (new) — your account is locked but kept intact. An admin can reactivate it later. Pick this if you might come back.
  - **Delete my account** (replaces the previous "soft delete") — your name, email, avatar, and login are wiped. The account row stays so the comments, tasks, and documents you authored remain visible (attributed to "Deleted user #{id}") instead of vanishing from your team's history. This is permanent.
  - **Hard delete** (admin only) — completely removes the row and everything attributed to it. Hidden from the user-facing dialog; only platform admins can do this from the admin page.

  All account-deletion paths now require you to transfer ownership of any projects you manage before submitting, so projects always have an active owner.

- The platform users page status column shows **Active**, **Deactivated**, or **Anonymized** in place of the old Active/Inactive label, and the "Reactivate" button is hidden for anonymized accounts (their data is gone — there's nothing to bring back).

- Anywhere a deleted user used to appear (comment authors, task assignees, mentions, calendar attendees, document collaborators), they now show as **Deleted user #{id}** with a neutral avatar instead of a stale name or email.

- Anonymized users are filtered out of "add member" and @-mention pickers, so you can't accidentally assign or mention someone whose account no longer exists.

- **Single Docker image for OSS and hosted deployments.** The dual-build setup (separate `*-infra` image with `INSTALL_INFRA_EXTRAS=true`) is gone — one image now serves every deployment, with the advanced tool integration enabled at runtime via env vars instead of at build time. The `INSTALL_INFRA_EXTRAS` build arg, the `requirements-infra.txt` extras file, and the `build-docker-infra` GitHub Actions job have been removed. Self-hosters get the same image we run; auditors can verify by inspection that the public image has no automation/event-publishing code paths.

- Bump lexical dependencies for a more stable document editor.

- Migrated the document editor to Lexical 0.44's Extension API. No user-visible behavior change, but the editor now uses `LexicalExtensionComposer` with `defineExtension` instead of the legacy `LexicalComposer` + plugin-list pattern, which clears the deprecation warning around `CodeNode` and aligns the editor with the upstream shadcn-editor architecture so future Lexical updates are easier to absorb.

### Fixed

- Read-only members can now create new documents from a template they have access to. Previously the copy required write access to the template, which defeated the point of templates being shared starters. Copying a non-template document still requires write access on the source.

- Deleting a document from the document settings page no longer fires two success toasts.

- Drag-scrolling a kanban board no longer smears a text selection across every card the pointer passes over.

- The document markdown converter now round-trips paragraph structure correctly. Toggling **Convert from markdown** previously turned a `\n\n` paragraph break into two stacked soft line breaks; converting back then re-emitted single newlines, so paragraphs steadily collapsed each time you toggled. Paragraph breaks now serialize as `\n\n` in markdown and parse back as real paragraphs, and shift+return soft breaks survive the round trip via the standard CommonMark hard-break syntax.

- The guild filter on **My Tasks** and **Created Tasks** silently ignored your selection — picking one or more guilds still showed tasks from every guild you belong to. The pages now narrow correctly.

- Documents owned by a departing user no longer become orphaned when the user leaves the initiative — whether they leave the guild, deactivate or delete their own account, get removed by an admin, or get unassigned via OIDC sync. The initiative's project managers automatically inherit ownership of those documents, so anyone who needs to find or clean up old work after a team move still can.

- Custom properties UI is now translated to Spanish and French. Previously, users on those locales saw English labels throughout the properties picker, manager, and filters.

### Removed

- **Automation engine, event publisher, and `aioboto3` dependency.** Domain-event fan-out for automation now lives entirely in the separately-deployed advanced tool service rather than in the FOSS backend. The bundled Kinesis publisher, the in-process automation engine, the Redis dependency, and the `automations_enabled` initiative flag (replaced by the generic `advanced_tool_enabled` slot) are all gone from the FOSS image. Fresh installs are unaffected; existing databases get a clean migration path.

## [0.42.1] - 2026-04-28

### Fixed

- The task edit page sometimes opened with the wrong status, priority, and recurrence shown until you nudged the page (added a tag, changed a property, etc.), then it would suddenly snap to the right values. All three fields now read from the task's own data on the first render instead of waiting for a delayed copy into local form state, so the form is correct the moment the task loads.

## [0.42.0] - 2026-04-23

### Added

- **Custom properties** on documents, tasks, and calendar events. Initiative managers define reusable properties from a new Custom Properties tab in initiative settings, picking from nine types (text, number, checkbox, date, date & time, URL, single-select, multi-select, or person). Attach them to any document, task, or event alongside tags; filter by them in every list; toggle per-property columns on the task and document tables; and see compact chips on kanban cards, document cards, and the calendar list view. Select/multi-select pickers support creating new options inline without leaving the entity.

### Removed

- Moving a project between initiatives. The "Initiative ownership" card is gone from project settings and `PATCH /projects/{id}` no longer accepts `initiative_id`. The move crossed a privacy boundary — the project and everything attached to it suddenly became visible to a different initiative's members — and each new initiative-scoped attachment (role permissions, tags, custom properties, calendar events) needed its own cascade rule to stay coherent. The cost of keeping the move correct grew faster than the demand for the feature. Create the project in the right initiative from the start; if you end up in the wrong one, duplicate it into the target and delete the original. A follow up will enable export and import for projects that will cover this use case.

### Changed

- Avatars are now consistent everywhere a person appears. The same deterministic color that powers the whiteboard cursor and Lexical editor caret tints the initials fallback in comments, task assignees, queue item owners, @-mention typeahead, calendar attendees, custom-property people pickers, and the collaboration badge. The collaboration badge and custom-property people cells also show uploaded profile pictures when available; previously both only ever showed initials. Non-user avatars like guild icons are unchanged.

## [0.41.0] - 2026-04-21

### Added

- New **smart link** document type. Create one from the dialog's new third tab by pasting a URL — Figma files, YouTube videos, Loom recordings, Vimeo videos, Google Docs/Sheets/Slides/Drawings, Miro boards, Airtable embed views, and Office docs are embedded inline; other URLs render a link card that opens in a new tab. Only the URL is stored; Initiative doesn't fetch anything from the link. Adding support for a new provider later automatically upgrades any existing smart-link docs whose URLs match that provider — no migration needed, since the provider is always derived from the URL at render time.
- Multiplayer cursors on whiteboards. When multiple users edit the same whiteboard document at once, each person now sees the others' pointer positions in real time, labeled with their name and tinted with their avatar color. Cursor updates piggyback on the existing Yjs awareness channel, so no new backend routes were needed.

### Changed

- Collaboration cursor colors are now deterministic per user and consistent across the app. The Lexical document editor caret, whiteboard cursor, and collaboration badge avatar all derive the same color from the user's id, so a given user shows up the same way everywhere. Previously the Lexical caret picked a random color per session and the avatar badge used a separate palette, so none of them agreed.

## [0.40.0] - 2026-04-20

### Added

- Optional Task Completion Visual Feedback effect when you mark a task you're assigned to as Done. Choose from None (default), Confetti, +1 Heart, Natural 20 d20 roll, Gold Coins, or Random (surprise me) under user settings → Interface. All effects use a unified 8-bit pixel-art aesthetic.
- Sound and haptic siblings to the task completion feedback. The new "Sound on task completion" and "Vibration on task completion" toggles in user settings → Interface play a short pop and trigger a two-pulse vibration (where supported) when you mark **any** task done — not just one assigned to you, since these are subtle enough to fire on every closeout. Both default to on; existing users get them enabled automatically. Haptics use the Capacitor Haptics plugin on native iOS/Android and fall back to the Web Vibration API in browsers that support it.

## [0.39.1] - 2026-04-18

### Added

- Fullscreen toggle in the document and whiteboard editors. The editor, its toolbars, action bar, and collaboration status take over the window for distraction-free writing or large-canvas diagramming. The Fullscreen button sits inline with the collaboration status badge above the editor.

### Fixed

- "Not tagged" filter in the Documents page tag tree view now actually filters to untagged documents. The page was computing the selection state but never sending the `untagged` query parameter to the backend, so selecting "Not tagged" returned every document instead of only the untagged ones.
- Leaving a collaborative document now tears the connection down cleanly. Other collaborators no longer see the leaver's avatar flicker (disappear briefly then reappear), and the "Collaboration connection failed — Maximum reconnection attempts reached" toast no longer fires after the user has navigated away from the document. The unmount cleanup in `useCollaboration` was using a soft, debounced `disconnect()` (a React Strict Mode optimization) instead of `destroy()`, leaving the provider alive in the global pool, the reconnect loop running, and the error callback still wired to the unmounted page's toast.

## [0.39.0] - 2026-04-14

### Added

- Improved task status UX: each status now has a customizable color and icon, with smart defaults driven by its category (backlog, todo, in progress, done). Kanban column headers show the status icon and a colored accent bar, and every status dropdown (kanban, project table/gantt rows, My Tasks, tag task lists, task edit page) now shows the icon beside the name and mirrors the active status color on the trigger border.

### Fixed

- Auto-redirect to the welcome/login page when the access token expires, instead of leaving the app in a broken state until the user manually refreshes. Shows a "Your session has expired" toast before the redirect.
  - Backend now returns `401 Unauthorized` (with `WWW-Authenticate`) for expired or invalid JWTs, invalid device tokens, and malformed token payloads, rather than `403 Forbidden`. Genuine authorization failures are unchanged.
  - Frontend 401 interceptor no longer silently swallows expired-session 401s on web cookie auth: an explicit session flag tracks whether a user is currently signed in, regardless of whether the in-memory bearer token was ever populated.
- Fix manual logout so previously-issued JWTs are actually invalidated server-side. The logout endpoint was using `AdminSessionDep` while `get_current_user_optional` used `SessionDep`, so in production the `current_user` object came from a detached session and the `token_version += 1` bump was silently dropped on commit. Previously-signed JWTs (and any still-cached HttpOnly cookie) stayed valid until natural expiry, letting users navigate back into protected pages by typing the URL after clicking "Sign out". The endpoint now uses a single `SessionDep` so FastAPI's per-request dependency cache hands both sites the same session, and the commit actually persists.

## [0.38.1] - 2026-04-12

### Fixed

- Fix whiteboard persistence losing edits on refresh / navigation
  - Add localStorage write-ahead cache so unsaved scenes survive page unload regardless of keepalive PATCH timing
  - Gate WhiteboardDocumentEditor on scene-ready state so Excalidraw's `initialData` captures the correct scene instead of the empty `useState` default
  - Skip stale Yjs initial sync in observer — only apply live updates from other users after bootstrap
  - Only clear `yjs_state` on PATCH when no active collaborators are in the room, preventing a data-loss window during periodic content-sync
  - Guard the document load effect so PATCH responses don't reset the live whiteboard scene mid-edit
- Fix whiteboard cache poisoning when rejoining a live room — a user rejoining with a stale local cache no longer clobbers the live room's state. The bootstrap now applies the Y.Map state whenever other collaborators are present, and local edits are gated behind the bootstrap decision so Excalidraw's initial mount `onChange` can't broadcast the cached scene.
- Whiteboards in collaboration mode now sync to `document.content` every 2s instead of 10s, matching the non-collab debounce. Narrows the stale-content window for non-collab readers and reduces the `yjs_state` / `content` desync window.

## [0.38.0] - 2026-04-10

### Added

- New `whiteboard` document type backed by Excalidraw
  - Create whiteboards via a new "Document type" dropdown on the Create Document dialog
  - Lazy-loaded canvas with full Excalidraw toolset (shapes, freehand, arrows, text, images)
  - Live collaboration via the existing Yjs WebSocket — whiteboard scene is mirrored to a single-key Y.Map and persisted alongside text documents
  - Theme syncs with the app's light/dark mode
  - Reuses the existing permissions, tags, comments, templates, and project-attachment infrastructure
  - Templates are filtered by document type so users don't accidentally copy a Lexical template into a whiteboard slot

### Fixed

- `normalize_document_content` is now type-aware so non-Lexical document content (whiteboard scenes, file metadata) isn't silently mutated to inject a Lexical `root` paragraph on save

## [0.37.0] - 2026-04-09

### Added

- Offline mode for the document editor
  - Persistent mode-aware toast when the device loses network connectivity
  - New "Offline" state in the collaboration status badge (now also shown in non-collaborative mode)
  - Autosave is skipped while offline and automatically retries on reconnect, so edits aren't lost
  - Uses `@capacitor/network` for accurate status on native, `navigator.onLine` on web

### Changed

- **React 18.3 → 19.2.** Bumped `react`, `react-dom`, `@types/react`, and `@types/react-dom` to 19.x. Required widening a drag-scroll hook's ref type to accept the new nullable `RefObject<T | null>`, importing `JSX` from `react` in a legacy Lexical `EmbedNode` (React 19 removed the global `JSX` namespace), and deleting two unused editor shim files that imported the now-removed `react-dom/test-utils`. All major peer deps (Lexical, Radix, TanStack Query/Router, cmdk, sonner, Testing Library 16) already declared `^19` support.
- **react-i18next 16 → 17** and **i18next 25 → 26.** Major bumps; react-i18next 17 requires i18next ≥ 26. None of i18next 26's breaking changes (`initImmediate`, legacy monolithic `format` function, `showSupportNotice`, `simplifyPluralSuffix`) are used in our config.
- Bumped `sqlmodel` 0.0.37 → 0.0.38 (backend ORM).
- Bumped `vite` 7.3.1 → 7.3.2, `msw` 2.12.14 → 2.13.0, `i18next-http-backend` 3.0.2 → 3.0.4, `@types/node` 25.5.0 → 25.5.2, `email-validator` 2.1.1 → 2.3.0, `python-multipart` 0.0.22 → 0.0.24.

### Fixed

- Document edits saved in non-collaborative mode are no longer overwritten by a stale `yjs_state` when re-enabling live collaboration. The document update endpoint now clears `yjs_state` and invalidates any empty in-memory collaboration room whenever content is written via the REST PATCH.

## [0.36.2] - 2026-04-08

### Added

- Table action menu in the document editor — click the chevron in any table cell to insert/delete rows and columns, toggle header rows/columns, or delete the table

### Fixed

- Fix tables shrinking from full width after deleting a column (changed table CSS from `w-fit` to `w-full`)
- Fix empty table rows/columns being removed during markdown round-trip (divider regex matched empty cells as header separators)

## [0.36.1] - 2026-04-06

### Added

- Global "Add Task" wizard dialog accessible from My Tasks, Tasks I Created, and the Command Center (Ctrl+K)
  - Multi-step flow: select guild → initiative → project → opens task composer on that project
  - Remembers last-used project for quick repeat task creation
  - Auto-skips steps when only one option exists (single guild or initiative)
  - Only shows projects the user has write access to

### Fixed

- Replace `imghdr` module with magic-bytes detection for Python 3.13 compatibility
- Fix double bottom inset on Android when the keyboard is visible (Capacitor SystemBars and safe-area plugin both applying insets)
- Remove `EdgeToEdge.enable()` to prevent conflict with safe-area plugin's inset management

## [0.36.0] - 2026-04-04

### Added

- Automations initiative tool (infra/paid feature, disabled by default)
  - Dual-layer feature gating: `ENABLE_AUTOMATIONS` env var (infrastructure) + per-initiative `automations_enabled` toggle
  - `automations_enabled` and `create_automations` permission keys with role-based access control
  - Stub `GET /automations` API endpoint for future pipeline integration
  - `GET /settings/automations-config` public endpoint for runtime feature discovery
  - Sidebar link with Zap icon, initiative settings toggle, and placeholder page
  - Build-time `VITE_ENABLE_AUTOMATIONS` flag for complete frontend tree-shaking in public builds
- Visual automation flow editor (n8n / Home Assistant style)
  - Drag-and-drop canvas powered by `@xyflow/react` with pan, zoom, and minimap
  - 5 node types: Trigger, Action, Condition (if/else branch), Delay, Loop (for-each)
  - Animated bezier edges with delete-on-hover
  - Node palette sidebar for dragging new nodes onto the canvas
  - Property inspector panel (Sheet) with type-specific forms
  - Automations list view with create/delete and card grid
  - 7 action types: send webhook, update task, send notification, add/remove tag, move to project, archive task
- Automation flow CRUD API with graph validation (DAG check, single trigger enforcement)
  - Full flow persistence to database (replaces localStorage)
  - Run history endpoints for execution logs
  - Frontend migrated to React Query hooks backed by backend API
- `POST /notifications/send` endpoint for engine-driven push notifications
- Redis service added to docker-compose (commented, for infra deployments)
- Automation engine backend infrastructure
  - Database tables: `automation_flows`, `automation_runs`, `automation_run_steps` with full RLS
  - `automation_engine` PostgreSQL role with BYPASSRLS for direct engine writes
  - Redis Streams event publisher for domain events (`task_created`, `task_updated`)
  - Service token authentication (`AUTOMATION_SERVICE_TOKEN`) for engine API callbacks
  - `REDIS_URL` config setting for event bus connectivity
- Dual Docker image CI/CD: publishes both `initiative` (public) and `initiative-infra` (paid) images
- Vite config now loads `.env` files from `backend/` directory for shared env vars
- Added Ctrl+S / Cmd+S keyboard shortcut to save in the document editor

### Fixed

- Cross-guild task/event links in My Calendar and My Tasks calendar view now navigate to the correct guild instead of the active guild

### Changed

- Bumped Lexical editor from 0.41 to 0.42 (all packages unified)
- Bumped asyncpg from 0.29.0 to 0.31.0
- Bumped httpx from 0.27.0 to 0.28.1
- Bumped SQLModel from 0.0.24 to 0.0.37
- Bumped pycrdt from 0.12.46 to 0.12.50
- Bumped PyJWT from 2.11.0 to 2.12.0
- Updated Orval to 8.6.2

### Removed

- Removed unused dependencies: `radix-ui` (unified), `@tanstack/router-devtools`, `autoprefixer`, `postcss`, `@tailwindcss/postcss`, `lodash`, `@types/lodash`
- Deleted unused `postcss.config.js`

## [0.35.0] - 2026-03-26

### Added

- Calendar events feature with Google Calendar-like UI
  - Initiative-scoped events with title, description, location, date/time, color, and recurrence
  - Attendee system with RSVP (pending, accepted, declined, tentative)
  - `events_enabled` toggle and `create_events` permission key on initiatives
  - Full CRUD, attendee management, RSVP, tags, and document attachment endpoints
- Reusable multi-view CalendarView component (day, week, month, year, list)
  - Month: multi-day spanning bars for all-day events, dot+time+title for timed events
  - Week/Day: positioned cards spanning full hour range with colored sidebar
  - Year: mini-month grids with per-event color dots or count badges
  - List: date, weekday, description, stacked attendee avatars with tooltip, time range
- Calendar sidebar link under each initiative with CalendarDays icon
- Event creation via clicking calendar day slots with date/time pre-fill
- Attendee picker using initiative members with searchable combobox
- Task recurrence selector reused for event recurrence

- Calendar view toggle on My Tasks and Created Tasks pages
- My Calendar page: cross-guild unified calendar combining tasks and events
  - Filters for status category, priority, and guild (persisted to local storage)
  - Events toggle to show/hide calendar events alongside tasks
  - Global calendar events backend endpoint (`GET /api/v1/calendar-events/global`)
- Filter and sort preferences persisted to local storage on My Tasks, Tasks I Created, My Projects, and My Documents pages
- Spanish and French translations for My Calendar page
- iCal (.ics) import/export for calendar events
  - Export events as `.ics` files (per-guild and cross-guild)
  - Import events from `.ics` files with preview and initiative selection
  - RRULE recurrence mapping (best-effort bidirectional conversion)
  - Export/import buttons on guild Events page and My Calendar page
  - Spanish and French translations for import/export UI

### Changed

- Replaced ProjectCalendarView with generic CalendarView component for project tasks
- Project task calendar now shows assignee avatars in list view
- Initiative settings: Calendar toggle alongside Queues under Advanced Tools

### Fixed

- Calendar event update endpoint now validates date ordering and 24-hour limit for timed events
- Document attachment on calendar events now scoped to guild, preventing cross-guild association

## [0.34.2] - 2026-03-18

### Fixed

- PWA manifest: fixed icon paths, split `any maskable` purpose into separate entries, added desktop and mobile screenshots for richer install UI

## [0.34.1] - 2026-03-03

### Changed

- Moved search/Cmd+K button from sidebar footer to top bar for better discoverability
- Aligned sidebar header, top bar, and activity sidebar header heights

### Fixed

- Lighthouse accessibility: added aria-labels to home link, progress bars, task status select, page size select, and searchable combobox
- Lighthouse SEO: added meta description and robots.txt
- Lighthouse performance: deferred Google Fonts loading, added Cache-Control headers for hashed static assets

## [0.34.0] - 2026-03-01

### Added

- French (Français) locale — full translation of all 19 frontend namespaces and backend email templates
- Image and Markdown file uploads for documents — images display with lightbox zoom, markdown files render with source/rendered toggle
- Heading anchor links (`#slug`) in both markdown file viewer and native Lexical editor — clicking scrolls to the matching heading

### Fixed

- `app_admin` role missing grants on `uploads` table — caused `permission denied` errors when serving uploaded files
- Markdown file upload rejected with 400 error when `python-magic` returns variant MIME type (e.g. `text/x-markdown`)

## [0.33.2] - 2026-02-28

### Added

- Column header sorting on the My Projects page (name and updated columns) with server-side sort support

## [0.33.1] - 2026-02-27

### Security

- Docker container now runs as non-root user (`app`, UID/GID 1000 by default) instead of root — compatible with rootless Docker and Podman. Set `PUID`/`PGID` environment variables to customize (e.g. `PUID=99 PGID=100` for Unraid's `nobody:users`)

### Fixed

- `app_admin` role missing grants on queue tables — caused `permission denied for table queues` errors for background jobs and seed scripts
- Added `ALTER DEFAULT PRIVILEGES` for `app_admin` so future migrations automatically inherit grants (previously only `app_user` had default privileges)

### Upgrade Notes

- **Uploads volume ownership**: The container now runs as a non-root user (UID 1000 by default). If file uploads fail after upgrading, fix ownership on the host: `chown -R 1000:1000 ./uploads`. Alternatively, set `PUID` and `PGID` to match your host user (e.g. `PUID=99 PGID=100` for Unraid)

## [0.33.0] - 2026-02-27

### Added

- Queue feature: turn/priority tracking with turn controls (start, stop, advance, previous, reset), per-item user/document/task linking, and tag support
- Queue DAC (Discretionary Access Control): user-level and role-based permissions with read/write/owner levels
- Queue settings page with details editing, role/user permission management, and delete
- Queue user permissions table: filtering by name, multiselect with bulk access change/remove, pagination, and "Add All" button
- Queue backend integration tests (19 tests covering CRUD, items, turns, DAC, and associations)
- Queue frontend and backend test factories
- Initiative-level feature flags: per-initiative toggle to enable/disable advanced tools like Queues; Advanced Tools accordion in create and settings dialogs
- Queues tab on initiative detail page when queues are enabled
- Queue list filter bar with search, active/inactive status filter, and initiative filter

### Changed

- Roles tab redesigned from data table to card-per-role layout with grouped permission switches and an Advanced Tools accordion, scaling to any number of permissions without horizontal scrolling
- Removed standalone "All Queues" sidebar link; queues are now accessed per-initiative

## [0.32.4] - 2026-02-26

### Security

- HTML and HTM files served via `/uploads/*` now force `Content-Disposition: attachment` and `Content-Security-Policy: script-src 'none'`, preventing stored XSS via uploaded HTML documents (GHSA-v38c-x27x-p584, reported by G3XAR).
- JWT tokens are now invalidated on logout and password change via server-side token versioning, preventing continued access with a captured token (GHSA-hww6-3fww-xw3h, reported by G3XAR). All active sessions will be signed out on first deployment of this update.

## [0.32.3] - 2026-02-26

### Added

- Dark Knight color theme: AMOLED true-black dark mode with dark maroon and bat-signal yellow accents
- ORC color theme: earthy green theme with vivid orc-skin green accents and cave/swamp dark mode
- Aboleth color theme: Monokai-inspired dark lair with vivid bioluminescent accent colors (lime, cyan, purple, orange, hot pink)
- Unicorn color theme: Bold and bright rainbow colors

## [0.32.2] - 2026-02-25

### Security

- Sensitive database fields are now encrypted at rest using Fernet (AES-128-CBC): AI API keys at platform, guild, and user levels; OIDC client secret; SMTP password. Existing data is migrated automatically via Alembic. The encryption key is derived from `SECRET_KEY`.
- User email addresses are now encrypted at rest. The `users` table stores an HMAC-SHA256 hash (`email_hash`) for fast indexed lookups and a Fernet ciphertext (`email_encrypted`) for display/sending; the plaintext `email` column is removed. Guild invite email addresses are also encrypted. Existing data is migrated automatically.
- Uploaded files now require authentication to access; the `/uploads/*` path no longer serves files to unauthenticated users. The backend validates the user's token from the `Authorization` header (reported by Adem Kucuk).
- Uploaded files are now restricted to members of the guild they were uploaded in. The backend tracks file→guild ownership in a new `uploads` table and returns 403 to authenticated users who are not members of the owning guild. Covers image attachments, document file uploads (PDF, DOCX, etc.), and files created by duplicate/copy/template operations. Pre-existing files without a database record remain accessible to any authenticated user for backwards compatibility.
- File-type documents (PDFs, DOCX, etc.) now enforce document-level read permission on download. A new `GET /api/v1/documents/{id}/download` endpoint replaces direct `/uploads/*` access for file documents; guild membership alone is no longer sufficient — the requester must have explicit read, write, or owner permission on the document. Inline viewing (`?inline=1`) and attachment download use the same permission check.
- Web sessions now use HttpOnly `SameSite=Lax` cookies instead of `localStorage` for JWT storage, eliminating XSS token theft risk and removing the JWT from browser history/server logs. The cookie is sent automatically for all requests including media (`<img>`, `<iframe>`); native (Capacitor) is unchanged and continues to use DeviceToken headers stored in Capacitor Preferences.
- Replaced `python-jose` with `PyJWT` for JWT handling. `python-jose` (through 3.3.0) has an algorithm confusion vulnerability with OpenSSH ECDSA keys and other key formats (similar to CVE-2022-29217) and is no longer maintained.
- Rate limiting added to `/uploads/*` (600 req/min) and `GET /documents/{id}/download` (30 req/min); file download access is now logged.
- Upgraded `python-multipart` from 0.0.9 to 0.0.22, fixing a DoS via malformed `multipart/form-data` boundary and an arbitrary file write via non-default configuration.
- Added Dependabot configuration (`.github/dependabot.yml`) for automated dependency update PRs on backend, frontend, and GitHub Actions.

### Changed

- Command Center search placeholder now reads "Search in \<guild name\>" instead of a generic string

## [0.32.1] - 2026-02-23

### Fixed

- My Tasks date groups (Overdue, Today, This Week, etc.) now respect the user's timezone — backend uses `AT TIME ZONE` with a `tz` query parameter instead of UTC `now()`
- `useAllDocumentIds` cache corruption after visiting the Initiatives page — fixed React Query key collision with `useDocumentsList`

### Changed

- Command Center shows project emoji icons and file-type-specific document icons (PDF, Word, Excel, PowerPoint) with color coding
- Extract shared `getDocumentIcon` / `getDocumentIconColor` helpers in `fileUtils.ts` — used by both Command Center and DocumentCard

## [0.32.0] - 2026-02-23

### Added

- Command Center (`⌘K` / `Ctrl+K`) for quick navigation to projects, tasks, documents, and pages with fuzzy search — accessible via sidebar shortcut badge or 3-finger tap on mobile
- Reusable `StatusMessage` component for consistent error states across detail pages
- Distinct 404/403 error messages on Project, Document, Tag, and Initiative detail pages using `Empty` card layout with contextual icons
- "Guild not available" page when navigating to a guild the user isn't a member of (replaces silent redirect)
- Rate-limit error message ("Too many requests") instead of misleading "Check your credentials" on login/register
- Row virtualization for DataTable using `@tanstack/react-virtual` — only visible rows exist in the DOM, tested with 10k tasks
- Virtualized Gantt view with sticky day headers and pinned task name column
- Virtualized Kanban columns (activates above 20 tasks per column) with memoized card components and DnD compatibility
- Collapse all / expand all buttons for sidebar initiative list and tag browser
- Memoized virtual cell rendering to prevent expensive re-renders during scroll

### Fixed

- Navigating to an inaccessible guild no longer poisons the active guild state, which previously caused "Unable to load" errors on the home page after redirect
- Dashboard "Recent Comments" no longer leaks comments from projects/documents the user lacks access to — filters by DAC permissions (direct + role-based)

### Security

- Add initiative-scoped RESTRICTIVE RLS policies to `tasks`, `task_statuses`, `subtasks`, and `task_assignees` — previously only had guild-level isolation

### Changed

- Vendored editor color picker (~1,800 lines) — replaced with existing shadcn-io color picker + Popover in font color and background color toolbar plugins
- Lazy-load editor color picker content so the `color` npm package is only fetched when a user opens the font/background color popover
- Lazy-load 4 profile settings pages (profile, notifications, interface, danger zone) — reduces index bundle by ~75 kB
- Replace pointless `React.lazy()` with static imports for `LexicalTypeaheadMenuPlugin` and `emoji-list` — both were already pinned to the editor chunk by co-located static imports, eliminating Vite "dynamically and statically imported" warnings
- Sidebar collapsed sections (initiatives, tags) no longer mount child DOM nodes — lazy-render on expand
- Skip `useSortable` hooks when drag-and-drop is disabled (sorting/grouping active) for better scroll performance
- Keep previous React Query data as placeholder for snappier page navigation
- - Replaced `sort_by`/`sort_dir` string parameters on the tasks list endpoint with a structured `sorting` JSON parameter (`SortField[]`) — enables multi-column sorting (e.g. date group then due date) using the same pattern as `conditions` uses `FilterCondition[]`
- Frontend task tables (`useGlobalTasksTable`, `TagTasksTable`, dashboard, route loaders) now pass `SortField[]` arrays instead of individual sort strings

## [0.31.5] - 2026-02-20

### Fixed

- `OIDC_ENABLED` env var no longer prevents admins from disabling OIDC via the UI — env var now only seeds on first boot instead of overriding the DB value on every read
- Guild switching no longer shows stale sidebar data — restored query cache invalidation on guild switch that was accidentally removed during React Query migration
- HTML `<strong>` tags rendered as literal text in delete confirmation dialogs — switched to react-i18next `Trans` component for proper bold rendering in initiative, guild, and settings dialogs (en + es locales)
- Defensive `Array.isArray` guard in document template queries to prevent crash on non-array data
- Admin initiative member role promotion (500 error) — endpoint referenced non-existent `.role` attribute on `InitiativeMember`; fixed to resolve roles via `role_id` FK
- Admin delete user dialog 404s when fetching initiative members across guilds — added admin endpoint `GET /admin/initiatives/{id}/members` that bypasses RLS
- Self-deletion dialog 404s when fetching initiative members across guilds — added user endpoint `GET /users/me/initiative-members/{id}` that bypasses RLS for owned initiatives

### Changed

- Centralized settings and AI settings mutation hooks (Phase 4a) — 13 new hooks in `useSettings.ts` and `useAISettings.ts` replace inline mutations across 7 settings pages/components; added `MutationOpts` to `useUpdateRoleLabels`
- Centralized remaining mutation hooks (Phase 4b) — 22 new hooks across `useAdmin.ts`, `useUsers.ts`, `useSecurity.ts`, and new `useImports.ts`; added `MutationOpts` to 11 existing hooks in `useComments.ts`, `useTags.ts`, `useNotifications.ts`; no `.tsx` file imports `useMutation` directly
- Centralized inline `useMutation` hooks for tasks, subtasks, task statuses, project members, role permissions, and project documents into domain hook files (`useTasks.ts`, `useProjects.ts`) — replaces ~50 inline mutations across 15 component/page files
- Consolidated standalone `useProjectFavoriteMutation` and `useProjectPinMutation` hooks into `useProjects.ts` as `useToggleProjectFavorite` and `useToggleProjectPin`
- All mutation hooks now accept an optional `MutationOpts` parameter, allowing callers to provide `onSuccess`, `onError`, `onSettled`, and other mutation options
- Added shared `MutationOpts` type (`frontend/src/types/mutation.ts`)
- Fixed `apiMutator` to merge request options (custom headers were silently ignored)
- Optimized database indexes: dropped 9 redundant indexes (PK-subsumed and unique-constraint-duplicated) and added 6 high-priority FK/reverse-lookup indexes for `task_assignees`, `initiative_members`, `project_permissions`, `document_permissions`, `initiatives`, and `projects`
- Synced model declarations (`index=True`) with actual database indexes for maintainability
- Test database setup is now fully automatic — `conftest.py` creates the `initiative_test` database and runs migrations on first test run, removing the need for manual `setup_test_db.sh`
- Centralized document mutations into `useDocuments.ts` — new hooks for create, upload, duplicate, copy, member CRUD (individual + bulk), role permission CRUD, and AI summary generation; replaces inline mutations across DocumentSettingsPage, DocumentDetailPage, DocumentsPage, CreateDocumentDialog, CreateWikilinkDocumentDialog, and DocumentSummary
- Centralized initiative mutations into `useInitiatives.ts` with `MutationOpts` support — replaces inline mutations in InitiativeSettingsPage

## [0.31.4] - 2026-02-20

### Fixed

- Mobile (Capacitor) app crash on startup — Orval-generated API requests used a hardcoded empty `baseURL`, causing them to hit the WebView origin instead of the backend server and receiving HTML instead of JSON
- Race condition where child provider effects fired API calls before `ServerProvider` set the backend URL from storage
- Locale file 404s on mobile — `navigator.language` returns full locale codes (e.g., `en-US`) but only `en/` directories exist; added `load: "languageOnly"` to i18next config
- `useProjectFavoriteMutation` and `useProjectPinMutation` crashing when toggling — `setQueryData` updaters treated paginated `ProjectListResponse` as a plain array
- Defensive `Array.isArray` guard in `initStorage()` and AppSidebar favorites to prevent crashes from unexpected Capacitor bridge responses

## [0.31.3] - 2026-02-20

### Added

- Paginated `GET /api/v1/projects/` endpoint with `page` and `page_size` query params (`page_size=0` returns all, preserving backward compatibility)
- `MentionEntityType` enum for mention search endpoint — replaces open-ended string parameter
- `PermissionKey` enum enforced at API, model, and database levels — adds CHECK constraint to `initiative_role_permissions.permission_key` column
- Alembic migration to add CHECK constraint for valid `permission_key` values

### Changed

- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated `useGlobalProjects` from raw `apiClient` to Orval-generated `listGlobalProjectsApiV1ProjectsGlobalGet` with generated query keys
- Removed custom `ProjectListResponse`, `MentionEntityType`, and `PermissionKey` types from `frontend/src/types/api.ts` — now generated from backend OpenAPI spec
- Moved `TaskWeekPosition` to `lib/recurrence.ts` and `CommentWithReplies` to `CommentSection.tsx` — `types/api.ts` is now a pure re-export of generated schemas

### Fixed

- Template document dropdown in CreateDocumentDialog not showing templates accessible via role-based permissions (only showed templates with explicit user permissions)
- Document/attachment uploads returning 422 error due to hardcoded `Content-Type: application/json` header overriding FormData auto-detection
- Subtask checklist items failed to load ("Unable to load checklist items right now") due to double-unwrapping of API responses in `useSubtasks` hook and `TaskChecklist` mutations

## [0.31.2] - 2026-02-19

### Added

- Centralized query key invalidation helpers (`frontend/src/api/query-keys.ts`) with domain-specific functions for consistent cache management

### Changed

- Migrated ~70 frontend files from manual `apiClient` calls to Orval-generated functions and React Query hooks
  - Pages: all project, task, document, initiative, settings, and user settings pages
  - Components: sidebar, comment section, import dialogs, bulk edit dialogs, task checklist, notifications
  - Hooks: tags, roles, AI settings, interface colors, version check, push notifications, realtime updates
  - Route loaders: all `ensureQueryData` calls updated to use generated fetchers and query keys
- Centralized frontend API query hooks into domain-specific hook files (`useDocuments`, `useProjects`, `useInitiatives`, `useComments`, `useNotifications`) following the `useTags` pattern — replaces inline `useQuery`/`useMutation` calls across pages with clean, reusable hooks that include error toasts and cache invalidation
- Created `usePagination` hook for reusable page/pageSize state management with URL search param sync
- Replaced manual query keys (e.g., `["projects"]`) with generated URL-based keys (e.g., `["/api/v1/projects/"]`)
- Replaced manual `queryClient.invalidateQueries()` calls with domain-specific helpers from `query-keys.ts`
- Orval config updated to `httpClient: "axios"` for clean return types (no discriminated union wrappers)
- API mutator updated to accept `AxiosRequestConfig` and prevent double URL prefixing with `baseURL: ""`
- Removed duplicate `TaskListResponse` and `DocumentListResponse` type definitions from `types/api.ts` in favor of Orval-generated versions
- Deleted `src/api/notifications.ts` — all consumers migrated to `useNotifications` hooks
- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated direct type imports from `@/types/api` to `@/api/generated/initiativeAPI.schemas` — types that exist directly in the generated Orval schemas are now imported from source, reducing reliance on the backward-compat alias layer

### Fixed

- Tasks endpoint returned no results when requesting tasks for a template project

## [0.31.1] - 2026-02-18

### Fixed

- Translation files were cached by the browser across deploys, causing newly added i18n keys to render as raw strings — translation fetches now include a version query param for cache busting

## [0.31.0] - 2026-02-18

### Added

- **Home sidebar mode** — clicking the logo now shows a user-centric sidebar (Discord-style) with personal navigation links instead of guild content
  - My Tasks (existing, refactored)
  - Tasks I Created — cross-guild list of tasks you created, with inline assignee display
  - My Projects — cross-guild list of projects you have access to
  - My Documents — cross-guild list of documents you own
  - My Stats (existing)
- `created_by_id` column on Task model to track who created each task
- `GET /tasks/?scope=global_created` endpoint — lists tasks created by the current user across all guilds
- `GET /projects/global` endpoint — lists projects the user can access across all guilds with pagination, guild filter, and search
- `GET /documents/?scope=global` endpoint — lists documents owned by the current user across all guilds
- Sequential Alembic migration naming convention (`YYYYMMDD_NNNN`) for chronological sorting
- Access controls in Create Project and Create Document dialogs via a collapsible "Advanced options" accordion
  - Role-based permission grants: assign access by initiative role at creation time
  - User-based permission grants: assign access to specific members at creation time
  - "Add all initiative members" opt-out toggle for projects (replaces invisible auto-add behavior)
- Shared `CreateAccessControl` component for role/user permission pickers

### Changed

- Sidebar now switches between Home mode (non-guild routes) and Guild mode (guild routes) based on the current URL
- MyTasksPage refactored to use shared `useGlobalTasksTable` hook, `GlobalTaskFilters`, and `globalTaskColumns` — shared across My Tasks and Tasks I Created pages
- Creating a project no longer auto-adds all initiative members as read — permissions are now explicitly controlled via the create dialog
- Project creation notifications are now scoped to only users who were granted access

### Fixed

- Post-baseline Alembic migration detection no longer crashes on startup — `init_db` now checks for `app_user` role existence instead of exact revision match
- Guild admins and initiative managers now follow DAC (Discretionary Access Control) for documents and projects — these roles no longer grant implicit owner-level access to every resource
- Guild admins can now add themselves to initiatives and manage initiative membership (previously required being an initiative manager)
- Collaboration WebSocket endpoint now uses pure DAC — matches REST endpoint behavior instead of bypassing access checks for admins/managers
- Fixed `handle_owner_removal` crash (`AttributeError: role`) when removing a member from an initiative
- Documents tag tree view: selecting "Not tagged" now filters server-side with correct pagination instead of client-side filtering per page
- Documents tag tree view: selecting a tag with no matching documents no longer replaces the sidebar with the empty state card
- AppSidebar crash when initiative query data is not an array

## [0.30.1] - 2026-02-16

### Added

- Auto-generated frontend TypeScript types and React Query hooks from the backend OpenAPI spec using Orval
  - Generated files in `frontend/src/api/generated/` committed to the repo so the frontend builds without a running backend
  - `frontend/src/types/api.ts` now re-exports generated types with backward-compatible aliases (e.g., `Task = TaskListRead`)
  - Custom Axios mutator (`frontend/src/api/mutator.ts`) preserves existing auth/guild interceptors
  - `pnpm generate:api` script to regenerate from a running backend
- CI check (`check-generated-types` job) that fails when generated frontend types drift from backend schemas
- `backend/scripts/export_openapi.py` to export OpenAPI spec without a running server (used by CI)

### Changed

- Backend Pydantic schemas now use `ConfigDict(json_schema_serialization_defaults_required=True)` so optional fields with defaults appear as required in the OpenAPI spec, producing cleaner generated types
- `frontend/src/types/api.ts` replaced ~800 lines of hand-maintained type definitions with re-exports from Orval-generated types
- Excluded `src/api/generated/**` from ESLint (Orval generates function overloads that trigger `no-redeclare`)
- CI backend test scoping now treats `app/schemas/` as shared infrastructure, triggering a full test run when schemas change
- Guild Dashboard landing page at `/g/:guildId/` with project health, velocity chart, upcoming tasks, recent projects, and initiative overview
- Guild switching now navigates to the dashboard instead of preserving the previous sub-path
- "All Projects" and "All Documents" links in the sidebar between favorites and initiatives
- Composite database indexes for query performance: tasks (project + archived, due date + status, updated_at), guild memberships (user + guild), and documents (updated_at)
- Squashed all 76 Alembic migrations into a single idempotent baseline migration — fresh installs no longer require `docker/init-db.sh` to pre-create database roles
- `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` are now **required** environment variables (previously fell back to `DATABASE_URL`, which silently ran the app as superuser without RLS enforcement)
- RLS is now always enforced — removed the `ENABLE_RLS` configuration flag
- Migrations always run using `DATABASE_URL` (superuser), fixing the env.py URL override bug that caused migrations to use the wrong connection
- Reorganized backend security architecture into two centralized service modules:
  - `rls.py` — Mandatory Access Control: guild isolation, guild RBAC (admin-only writes), initiative membership, and initiative RBAC via PermissionKey
  - `permissions.py` — Discretionary Access Control: project/document-level read/write/owner permissions with visibility subqueries
- Centralized guild admin enforcement across all endpoints via `rls_service.is_guild_admin()` and `rls_service.require_guild_admin()`
- Moved initiative security checks (`is_initiative_manager`, `check_initiative_permission`, `has_feature_access`) from initiatives service to `rls.py` (backward-compatible re-exports preserved)
- Replaced duplicated permission logic in endpoint files (projects, documents, tasks, tags, imports, collaboration) with shared helpers from `permissions.py`
- Consolidated visibility subquery patterns (`visible_project_ids_subquery`, `visible_document_ids_subquery`) to eliminate duplication across listing endpoints

### Removed

- `ENABLE_RLS` environment variable — RLS is always active; remove this from your `.env` if present
- `init_models()` backwards-compatibility alias (use `import app.db.base` directly)
- `docker/init-db.sh` — database role creation is now handled by the baseline migration itself
- 76 individual migration files replaced by single baseline (existing v0.30.0 databases upgrade seamlessly)

### Upgrade Notes

- **From v0.30.0**: No action needed — the baseline migration is a no-op for existing databases. You can safely remove `docker/init-db.sh` if present.
- **From pre-v0.30.0 (v0.14.1–v0.29.x)**: The application will detect the old schema and exit with instructions. Run the upgrade script before starting:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/beyonders-studio/initiative/main/scripts/upgrade-to-baseline.sql \
    -o upgrade-to-baseline.sql
  psql -v ON_ERROR_STOP=1 -f upgrade-to-baseline.sql "$DATABASE_URL"
  ```
  If psql is not available on your host (e.g. Synology, Unraid), pipe through the Postgres container:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/beyonders-studio/initiative/main/scripts/upgrade-to-baseline.sql | \
    docker exec -i initiative-db psql -v ON_ERROR_STOP=1 -U initiative -d initiative
  ```
  Then restart the application. The baseline migration will create database roles, RLS policies, and grants automatically.

## [0.30.0] - 2026-02-15

### Added

- Full internationalization (i18n) infrastructure with react-i18next and namespace-based translation loading
  - 16 translation namespaces covering all app areas: auth, nav, projects, tasks, documents, settings, guilds, initiatives, tags, stats, import, notifications, landing, errors, dates, common
  - Language selector in user interface settings (infrastructure ready for additional languages)
  - User `locale` preference stored in database with Alembic migration
  - Backend email i18n with JSON-based template loader and `{{variable}}` interpolation
  - Backend error code constants (`messages.py`) mapped to frontend-localized messages via `errors.json`
- All user-facing strings externalized across the entire application:
  - Auth flow (login, register, password reset, email verification)
  - Navigation, sidebar, and guild switcher
  - Project CRUD, settings, permissions, and kanban/table/timeline views
  - Task editing, assignments, recurrence, priorities, and status management
  - Document editor toolbar, comments, mentions, and emoji picker
  - Initiative and guild management, member tables, and invite flows
  - User settings (profile, security, notifications, interface, import/export)
  - Platform admin pages (users, settings, OIDC configuration)
  - Statistics and reporting pages
  - Landing page with all marketing copy
  - Email templates (verification, password reset, task assignment, mentions, overdue notifications)
- Spanish (es) locale — complete translations for all 16 frontend namespaces and backend email templates (these are AI generated translations, contributions wanted)
- Locale-aware AI content generation (subtasks, descriptions, document summaries respond in user's language)
- `useDateLocale` hook for date-fns locale resolution across the app
- Locale key parity test (vitest) to catch missing/extra translation keys in CI

## [0.29.1] - 2026-02-13

### Fixed

- Hotfix docker entry script

## [0.29.0] - 2026-02-13

### Added

- OIDC claim-to-role mapping: automatically assign users to guilds and initiatives based on OIDC token claims (e.g., `groups`, `realm_access.roles`) on every login
  - Configurable claim path and mapping rules in Platform Settings > Auth
  - Supports guild and initiative target types with role selection
  - OIDC-managed memberships tracked separately from manual assignments; manual memberships are never overwritten
  - Stale OIDC-managed memberships automatically removed when claims change
- OIDC refresh token periodic re-sync: stores encrypted refresh tokens and periodically re-fetches userinfo claims in the background, keeping guild/initiative memberships in sync without requiring re-login
  - 5-minute poll cycle with 15-minute per-user sync interval
  - Automatic token rotation support; graceful handling of revoked tokens
  - `offline_access` added to default OIDC scopes for refresh token issuance
- Extracted background task runner into dedicated `background_tasks.py` module
- PKCE (S256) support for OIDC authentication, required by many identity providers
- Multi-sort support for task list API (`sort_by=date_group,due_date&sort_dir=asc,asc`)
- New cinematic landing page with parallax starfield, scroll-driven animations, interactive screenshot lightbox, and dark/light theme support
- No-guild empty state for users with no guild membership after login, with options to create a guild, redeem an invite, or log out
- "Source" column in guild and initiative member tables showing whether membership is managed by OIDC or manual

### Changed

- Renamed `OIDC_DISCOVERY_URL` env variable to `OIDC_ISSUER` (old name still works as fallback); issuer URL no longer requires `/.well-known/openid-configuration` suffix
- Guild deletion now uses a name-confirmation dialog instead of browser prompt
- Logout now clears the React Query cache to prevent stale data when switching accounts

### Fixed

- Role-based write users now appear in task assignee dropdowns (previously only explicit user permissions were considered)
- My Tasks page now sorts by date group (overdue, today, this week, this month, later) then by due date, matching the visual grouping order
- `BEHIND_PROXY=true` now passes `--proxy-headers` and `--forwarded-allow-ips` to Uvicorn so real client IPs appear in logs and `request.client.host` (#92)
- Users with no guild membership no longer get 500 errors; backend returns 403 with descriptive message
- Documents on project dashboard are now filtered by user's document-level permissions (guild admins see all)
- Project settings button in sidebar now correctly appears for users with role-based write access
- Removing a user from a guild or initiative now clears their task assignments
- OIDC sync membership removal now cleans up task assignments
- Fixed loading state flicker on no-guild screen caused by `useGuilds` dependency cycle

## [0.28.0] - 2026-02-11

### Added

- Server-side pagination for tasks: `GET /tasks/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated results with total count (`page_size=0` returns all for drag-and-drop views)
  - Server-side sorting for tasks with support for title, due date, start date, priority, created/updated timestamps, and manual sort order
  - Pagination and server-side sorting controls on My Tasks page and tag tasks table, with page synced to URL and hover prefetching
- Server-side pagination and sorting for documents: `GET /documents/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated and sorted results with total count
  - `GET /documents/counts` lightweight endpoint returning per-tag document counts for the tag tree sidebar
  - Pagination controls (prev/next, page size selector, page in URL) for all three document views (list, grid, tags)
  - Data prefetching on hover over pagination buttons for instant page transitions
- Role-based access control for projects and documents: grant read or write access to an entire initiative role as well as adding users individually
  - Role Access section in project and document settings pages for managing role-based permissions
  - Bulk role access management: grant or revoke role-based permissions across multiple selected documents at once
  - `my_permission_level` field in project and document API responses indicating the current user's effective access level
- Persistent storage abstraction (`storage.ts`) backed by Capacitor Preferences on mobile and localStorage on web, preventing data loss when mobile OS clears localStorage under memory pressure

### Changed

- Project settings page reorganized into tabbed layout (Details, Access, Task statuses, Advanced)
- Document settings page reorganized into tabbed layout (Details, Access, Advanced)
- Bulk edit access dialog restructured into Roles and Users tabs, each with grant/revoke action selector
- All frontend localStorage usage migrated to the new storage abstraction (~15 files)

## [0.27.0] - 2026-02-10

### Added

- Initiative-scoped Row-Level Security: users must be an initiative member to see its data (initiatives, projects, documents, roles). Guild admins and superadmins bypass this layer.

### Fixed

- My Stats page returning all zeros after RLS enforcement (endpoint now uses UserSessionDep for proper RLS context)
- User profile and self-update endpoints returning empty initiative roles under RLS enforcement
- Missing `guild_id` on initiative member records when creating initiatives or adding members, causing members to be invisible under RLS
- Stale initiative data returned after create/update due to SQLAlchemy identity map caching
- 64 pre-existing test failures caused by test infrastructure not keeping up with RLS, DAC, and role system changes

## [0.26.0] - 2026-02-08

### Added

- Per-channel notification preferences: independent Email and Mobile App (push) toggles for each notification category
- Email notifications for mentions, comments, and replies (previously only had push and in-app)
- Mobile App column on notification preferences page (shown when FCM is enabled)

### Changed

- In-app bell notifications now always fire regardless of user preferences
- Notification preferences page redesigned as a table with Email and Mobile App columns

### Fixed

- Mentions preference (`notify_mentions`) was missing from user update schemas, preventing it from being changed via API

## [0.25.5] - 2026-02-07

### Added

- Email column in project and document access tables for easier member identification

### Fixed

- Task status editing no longer crashes with 500 error for custom roles
- Task status management now uses project-level write access (DAC) instead of requiring initiative manager role
- Guild admins can now see all guild members in the Users settings table (was only visible to platform admins)

## [0.25.4] - 2026-02-07

### Fixed

- Attempt: My Tasks page now shows tasks from all guilds the user belongs to, not just the active guild (RLS SELECT policies now check membership instead of active guild)

## [0.25.3] - 2026-02-07

### Fixed

- Mobile deep links now correctly forward device token auth

## [0.25.2] - 2026-02-07

### Fixed

- OIDC login on mobile now issues a long-lived device token instead of a short-lived JWT, so sessions persist across app restarts

## [0.25.1] - 2026-02-07

### Fixed

- Tag badges now link to their tag detail page across all views (My Tasks, project table, Kanban, project previews, documents)
- Added tags column to My Tasks table
- Create project dialog no longer reopens after clicking cancel or create
- Make heading and filter styling more consistent across pages

## [0.25.0] - 2026-02-06

### Added

- **Row Level Security (RLS) enforcement** across all API endpoints
  - Database-level access control ensures users can only access data within their guild
  - All guild-scoped endpoints now set RLS context (user, guild, role) before querying
  - Super admin bypass via `app.is_superadmin` session variable
  - RLS policies added for tags, document_links, task_tags, project_tags, and document_tags tables
  - Guild table now has command-specific policies (SELECT/INSERT/UPDATE/DELETE) instead of a single blanket policy
  - Guild memberships allow cross-guild SELECT for own memberships (needed for guild list, leave checks)
  - NULLIF-safe policies prevent empty string cast crashes (fail-closed with 0 rows instead of 500 errors)

### Changed

- Admin endpoints now use dedicated admin database sessions (bypass RLS for cross-guild platform operations)
- Registration, invite acceptance, and account deletion use admin sessions (bootstrapping operations that span guilds)
- Database sessions pin their connection for the entire request lifetime to prevent RLS context loss after commits

### Upgrade Notes

**Docker deployments** should update their setup to enable RLS enforcement:

1. **Add the init script** — copy `docker/init-db.sh` from the repository into a `docker/` directory next to your `docker-compose.yml`. This script creates two PostgreSQL roles:
   - `app_user` — RLS-enforced, used for normal API queries
   - `app_admin` — BYPASSRLS, used for migrations and background jobs

2. **Update `docker-compose.yml`** — add the following to your `db` service:

   ```yaml
   services:
     db:
       environment:
         APP_USER_PASSWORD: ${APP_USER_PASSWORD:-app_user_password}
         APP_ADMIN_PASSWORD: ${APP_ADMIN_PASSWORD:-app_admin_password}
       volumes:
         - ./docker/init-db.sh:/docker-entrypoint-initdb.d/01-create-roles.sh
   ```

   And add these environment variables to your `initiative` service:

   ```yaml
   services:
     initiative:
       environment:
         # RLS-enforced connection (app_user role, no BYPASSRLS)
         DATABASE_URL_APP: postgresql+asyncpg://app_user:${APP_USER_PASSWORD:-app_user_password}@db:5432/initiative
         # Admin connection for migrations and background jobs (app_admin role, BYPASSRLS)
         DATABASE_URL_ADMIN: postgresql+asyncpg://app_admin:${APP_ADMIN_PASSWORD:-app_admin_password}@db:5432/initiative
   ```

   See `docker-compose.example.yml` for a complete reference.

3. **Fresh databases only** — the init script runs on first `docker-compose up` (when the postgres data volume is empty). For existing databases, the Alembic migration (`20260207_0040`) creates the roles automatically. You will still need to set `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` environment variables.

4. **Backward compatible** — if `DATABASE_URL_APP` is not set, the app falls back to `DATABASE_URL` and RLS remains inert (existing behavior).

## [0.24.0] - 2026-02-06

### Added

- Bulk edit tags for tasks and documents (add/remove modes)
- Bulk edit access permissions for documents (grant/revoke modes)
- Tag detail page now uses a tabbed layout (Tasks, Projects, Documents) with full filtering, sorting, and inline status/priority editing

### Fixed

- Duplicate rows appearing in task table when sorting with filters applied
- Guild switching no longer flashes back and forth between old and new guild before settling
- Tags now carry over when recurring tasks create their next instance

## [0.23.0] - 2026-02-05

### Added

- Tags view on Documents page for browsing documents by tag
  - Collapsible tag tree with document counts and hierarchical expand/collapse
  - Click to filter by tag, Ctrl/Cmd+Click for multi-select (OR filtering)
  - "Not tagged" filter for documents without any tags
  - Responsive layout: side panel on desktop, collapsible header on mobile
  - Tags view is now the default view mode (Tags / Grid / List)

### Fixed

- Multi-tab guild stability: opening different guilds in separate tabs no longer causes rapid switching or ping-pong loops
  - Removed server-side `active_guild_id` tracking (each tab derives guild from URL)
  - Removed cross-tab localStorage sync that caused cascading re-renders
  - Removed `POST /guilds/{id}/switch` endpoint (no longer needed with guild-scoped URLs)

## [0.22.0] - 2026-02-04

### Added

- Guild-scoped URLs for shareable cross-guild links
  - Routes changed from `/projects/47` to `/g/:guildId/projects/47`
  - Links can be shared directly without losing guild context
  - Old URLs automatically redirect to new format for backward compatibility
  - Cross-guild navigation on My Tasks page works without manual guild switching

## [0.21.0] - 2026-02-04

### Added

- Guild-scoped tags for tasks, projects, and documents
  - Create tags with custom names and colors via TagPicker component
  - Assign multiple tags to tasks, projects, and documents
  - Filter by tags in project tasks view, projects page, and documents page
  - Tags displayed on project cards, document cards, and task table rows
  - Tag browser in sidebar with nested hierarchy support (e.g., "books/fiction")
  - Tag detail page showing all entities with a specific tag
  - Tags preserved when duplicating tasks, projects, or documents
  - Case-insensitive unique names per guild
- Document wikilinks with `[[Document Title]]` syntax
  - Type `[[` in the editor to search for documents in the current initiative
  - Autocomplete shows existing documents, with option to create new ones
  - Resolved links display in blue; unresolved links display in grey/italic
  - Click links to navigate or create documents
  - Backlinks section shows documents that link to the current document
  - Document titles must be unique within each initiative

### Fixed

- Race condition in recording recent project views causing duplicate key errors

## [0.20.1] - 2026-02-03

### Changed

- Initiative settings members table now has separate Name and Email columns
- Removing a member from an initiative now shows a confirmation dialog warning that explicit access to all projects and documents will be removed

### Fixed

- Members table filter input now works correctly
- Users dropdown now refreshes when switching guilds (was showing stale data from previous guild)

## [0.20.0] - 2026-02-03

### Added

- Configurable role permissions per initiative
  - Four permission keys: `docs_enabled`, `projects_enabled`, `create_docs`, `create_projects`
  - Roles tab in Initiative Settings to manage role permissions
  - Create custom roles with configurable permissions
  - Rename and delete custom roles
  - Sidebar hides Docs/Projects based on role permissions
  - Create buttons hidden based on role permissions
  - Built-in PM role has locked permissions; Member role is configurable
  - Does not override DAC for project/document resources (direct links still work with explicit access)
- Document AI Summary feature
  - "Summarize with AI" generates 2-4 paragraph summaries of native documents
  - New side panel with tabs for AI Summary and Comments
  - Panel toggle button in document header
  - Summary persists when switching between tabs
  - Converts Lexical editor content to Markdown for better AI comprehension
- Uploadable file documents (PDF, Word, Excel, PowerPoint, text, HTML)
  - Upload files via "Upload file" tab in create document dialog
  - PDF viewer with zoom controls and continuous page scrolling
  - Office documents show download prompt (browser preview not supported)
  - 50 MB file size limit with client-side validation
- Lazy loading for document detail page (Editor and PDF viewer load on demand)
- Comment editing for authors
  - Users can edit their own comments on tasks and documents
  - Edit button appears next to Reply for author's own comments
  - Inline edit mode with Save/Cancel buttons
  - "(edited)" indicator shows when a comment has been modified

### Changed

- Document comments moved from inline section to side panel
- AI-generated subtasks and descriptions now include initiative and project names for better context
- Only guild admins and initiative project managers can pin/unpin projects
- Pin button is now hidden for users who cannot pin (instead of showing disabled)
- Refactored project access control to discretionary access control (DAC) model
  - Task assignments are automatically removed when a user loses write access (permission removed or downgraded to read)
  - Removed `members_can_write` toggle from projects
  - Added `read` permission level (owner, write, read)
  - Access is now determined solely by explicit permissions in the project_permissions table
  - On project creation, all initiative members are automatically granted read access
  - When a user leaves an initiative, their project permissions are cleaned up automatically
  - When a project owner is removed from an initiative, all initiative PMs get owner access
  - Project settings page now shows a permissions table instead of the old toggle + overrides UI
- Refactored document access control to discretionary access control (DAC) model
  - Added `owner` permission level to documents (owner, write, read)
  - Document creators automatically become owners with full management rights
  - Owners can manage permissions, delete, and duplicate documents without being initiative PMs
  - Added individual member management endpoints (POST/PATCH/DELETE) for document permissions
  - When a document owner is removed from an initiative, all initiative PMs get owner access
  - Document settings page now shows a permissions table instead of the old toggle UI

### Fixed

- Document editor no longer appears blank when collaboration mode is loading
- Collaboration now shows proper status progression: "Connecting..." → "Syncing..." → "Live editing"
- Fixed stuck "Syncing..." spinner after navigating between documents quickly
- Collaboration connection now automatically reconnects when dropped
- Error toast now appears when collaboration fails, with automatic fallback to autosave mode

## [0.19.1] - 2026-01-30

### Fixed

- Task filters now properly reset when navigating between projects

## [0.19.0] - 2026-01-30

### Added

- Guild sidebar context menu (right-click)
  - All members: View initiatives, Copy guild ID, Leave guild
  - Guild admins: View members, Invite members (creates & copies invite link), Create initiative, Guild settings
  - Leave guild checks eligibility (last admin, sole PM of initiatives) before allowing departure
  - Actions automatically switch to the target guild's context when needed

### Changed

- Migrated frontend routing from React Router to TanStack Router
  - Type-safe routing with validated route params and search params
  - Improved React Query integration for data prefetching
- Removed initiative filter from My Tasks page (was showing only active guild's initiatives, making it redundant)

### Fixed

- Switching guilds now properly refreshes project, initiative, and document lists
- Connect and login pages no longer require double-clicking to navigate on mobile
- Live collaboration and real-time updates now work on mobile apps

## [0.18.0] - 2026-01-28

### Added

- Platform admin blocker resolution for user deletion
  - New admin endpoints to delete guilds, promote guild members, and promote initiative members
  - Enhanced deletion eligibility response includes detailed blocker info with promotable members
  - Delete user dialog now shows "Resolve Blockers" step with inline actions
  - Admins can promote another member to guild admin or delete the guild entirely
  - Admins can promote another member to project manager for initiatives
  - Auto-advances to next step when all blockers are resolved
- PostgreSQL Row Level Security (RLS) for guild data isolation
  - Database-level access control ensures users can only access data within their current guild
  - Defense-in-depth protection in addition to application-level access controls
  - Denormalized `guild_id` columns added to all tier 2/3 tables for efficient policy evaluation
  - Automatic triggers maintain guild_id consistency when parent relationships change
  - New `RLSSessionDep` dependency for routes that need database-level access control
  - Admin bypass role (`app_admin`) for migrations and background jobs
- Role-based platform admin system with promote/demote functionality
  - Multiple users can now be platform admins (no longer limited to user ID 1)
  - Platform admins can promote/demote other users via Platform Users settings page
  - Protection against demoting the last platform admin
  - Platform roles and guild roles are now completely independent
  - Guild Users page now manages guild roles separately from platform roles
- `ENABLE_PUBLIC_REGISTRATION` environment variable to control public registration
  - When set to `false`, all new users must register via an invite link
  - Bootstrap (first user) registration is always allowed regardless of setting
  - Landing page and register page adapt UI based on this setting
- Platform admins can now create guilds when `DISABLE_GUILD_CREATION=true`
  - Regular users are still blocked from creating guilds when this flag is enabled
  - The `can_create_guilds` field in user responses now reflects platform admin status

### Changed

- **Docker users**: `DATABASE_URL_ADMIN` environment variable is now required for RLS migrations
  - RLS migrations need superuser privileges to create the `app_admin` role with `BYPASSRLS`
  - Add to your docker-compose: `DATABASE_URL_ADMIN: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD:-initiative}@db:5432/initiative`
  - This URL uses the `postgres` superuser; the regular `DATABASE_URL` continues using the restricted `initiative` user
- Destructive actions now use confirmation dialogs instead of browser alerts

## [0.17.0] - 2026-01-27

### Added

- Switchable color themes with user preference persistence
  - Theme selector in Settings → Interface
  - Three built-in themes: Kobold (default indigo), Displacer (Catppuccin pastels), Strahd (Dracula gothic)
  - Extensible theme system for adding custom themes
  - Themes apply to both light and dark modes
- Spell check suggestions in document editor context menu
  - Right-click on misspelled words to see correction suggestions
  - Uses Typo.js with dictionaries loaded from CDN on first use
  - Works consistently across Chrome, Firefox, and other browsers
- Priority badge is now a clickable dropdown to change task priority inline

### Fixed

- Document page comments now wrap below editor at larger screen widths for better readability
- Past due dates now show green (success) when task is completed instead of always showing red
- Bulk edit dialog now correctly uses "Urgent" priority value instead of invalid "Critical"
- URLs in comments are now clickable and properly wrap instead of overflowing the container
- URLs in task descriptions (markdown) now properly wrap instead of overflowing
- Layout no longer disappears when navigating to lazy-loaded pages (shows spinner in content area)
- Version update popup no longer appears when client version is ahead of server
- Dismissed version popup no longer reappears on page refresh (persisted to localStorage)
- Fixed footer alignment in version update dialog
- Version dialog changelog now renders nested list items

## [0.16.0] - 2026-01-25

### Added

- Live collaborative document editing using Yjs CRDT
  - Multiple users can edit the same document simultaneously in real-time
  - Collaborator presence indicators showing who is currently editing
  - WebSocket-based synchronization with automatic reconnection
  - Graceful fallback to autosave mode if collaboration connection fails
  - New database column `yjs_state` stores collaborative document state

## [0.15.2] - 2026-01-24

### Fixed

- Mobile OIDC deep link handler now works from login page (was only active after authentication)

## [0.15.1] - 2026-01-24

### Added

- Mobile OIDC/SSO login support using deep links
  - OIDC authentication now works on the mobile app
  - Uses Capacitor Browser plugin to open system browser for OAuth flow
  - Custom URL scheme (`initiative://`) handles callback redirect
  - Mobile redirect URI displayed in auth settings page

### Fixed

- Document export now uses document title in filename instead of generic timestamp

## [0.15.0] - 2026-01-23

### Added

- Enabled speech-to-text plugin on document editor. Uses browser speech recognition APIs. Tested working on Chrome and Edge.
- Responsive document editor toolbar
  - Compact overflow menu on screens below 1024px with all formatting options
  - Full inline toolbar on larger screens
- Alignment buttons converted to a dropdown menu for a more compact toolbar

### Fixed

- Speech-to-text now normalizes transcripts across browsers (auto-spacing, auto-capitalization)
- Speech recognition preview bubble no longer hidden behind toolbar
- Android APK version now syncs with main VERSION file (was stuck at 1.0)

## [0.14.1] - 2026-01-23

### Added

- Licensed the project with AGPLv3

### Fixed

- Rolling recurrence now preserves the original due time instead of inheriting the completion timestamp

## [0.14.0] - 2026-01-22

### Added

- Enhanced comments with mentions, threading, and notifications
  - @mention syntax for users (`@[Name](id)`) with autocomplete popup
  - Entity mentions for tasks (`#task[Title](id)`), documents (`#doc[Title](id)`), and projects (`#project[Name](id)`)
  - Threaded replies with visual indentation (max 3 levels)
  - Reply button on each comment with inline reply form
- Comment notifications with intelligent deduplication
  - Notify users when mentioned in comments
  - Notify task assignees when their task is mentioned
  - Notify task assignees when someone comments on their task
  - Notify document authors when someone comments on their document
  - Users already notified via one mechanism won't receive duplicate notifications
- Mentions toggle in user notification settings

### Fixed

- Document editor: heading spacing, horizontal rule spacing, code background, url modal background

## [0.13.0] - 2026-01-21

### Added

- AI Integration with BYOK (Bring Your Own Key) support
  - Hierarchical settings: Platform -> Guild -> User with inheritance and override controls
  - Support for OpenAI, Anthropic, Ollama (local), and custom OpenAI-compatible providers
  - Test connection validates API keys and model names, fetches available models
  - Searchable model combobox with custom model name support
- AI-powered task features (when AI is enabled)
  - Generate description: AI button next to description field auto-generates task descriptions
  - Generate subtasks: AI button in subtasks section suggests actionable subtasks with selection dialog

### Changed

- Anthropic test connection now fetches models dynamically from their API instead of hardcoded list
- Model combobox now fetches available models automatically when opened (improved UX)

## [0.12.5] - 2026-01-20

### Added

- Pull-to-refresh on mobile app to refresh data without reloading the page (My Tasks, Projects, Project Detail, Initiatives)

### Fixed

- Android hardware back button now navigates through router history instead of exiting the app

### Changed

- Inverted app icon. Now when it's themed, its more legible.

## [0.12.4] - 2026-01-18

### Fixed

- FirebaseRuntime plugin now registers before Capacitor bridge initialization

## [0.12.3] - 2026-01-17

### Fixed

- Push notifications now work on self-hosted deployments (fixed FCM config URL)

## [0.12.2] - 2026-01-17

### Fixed

- Task position no longer changes when updating status via dropdown in table view
- Safe area insets now work correctly on Samsung One UI devices

## [0.12.1] - 2026-01-17

### Fixed

- Server crash on startup due to missing request parameter in FCM config endpoint rate limiter

## [0.12.0] - 2026-01-17

### Added

- Push notifications for mobile devices via Firebase Cloud Messaging (FCM)
- Runtime Firebase initialization - no APK rebuild required for self-hosted instances
- Five notification channels for Android: Task Assignments, Initiative Invites, New Projects, User Approvals, and Mentions
- Custom white notification icon for proper Android notification tray display
- Push notification settings in user notification preferences
- Automatic FCM config endpoint for mobile app initialization (`/api/v1/settings/fcm-config`)
- Push token management with automatic cleanup of invalid tokens

## [0.11.1] - 2026-01-16

### Fixed

- Device tokens now display actual device name (e.g., "Jordan's S25 Ultra") instead of generic "Mobile Device"

## [0.11.0] - 2026-01-16

### Added

- Capacitor mobile app support for iOS and Android
- Device authentication tokens for persistent mobile login (never expire)
- Server URL configuration page for connecting to self-hosted instances
- Safe area handling for edge-to-edge display on Android
- Android APK automatically built and attached to GitHub releases
- Device token management in user settings (view and revoke mobile sessions)

### Changed

- Renamed "API Keys" settings tab to "Security" (now includes device management)
- Mobile auth uses device tokens instead of expiring JWTs
- Token storage uses native Preferences API for persistence on mobile

## [0.10.0] - 2026-01-14

### Added

- Task import from external platforms (Todoist CSV, Vikunja JSON, TickTick CSV)
- Import settings page with extensible platform support (Trello, Asana coming soon)
- Section/bucket-to-status mapping with smart suggestions based on names
- Subtask and priority mapping during import

## [0.9.0] - 2026-01-14

### Added

- Task archival feature: archive tasks to hide them from default views
- "Show archived" filter toggle in project task views
- Archive/Unarchive button on task detail page
- "Archive done tasks" bulk action in table view and kanban done columns
- Archive button in bulk selection panel for archiving multiple tasks at once
- Confirmation dialog for archive actions showing task count

## [0.8.0] - 2026-01-13

### Added

- @mention support for tagging initiative members in documents
- Notifications when users are mentioned in documents
- User preference to enable/disable mention notifications
- Autosave for documents with toggle checkbox (enabled by default)

### Changed

- Document editor upgraded to shadcn-editor with improved toolbar and formatting options
- Image uploads now use server-side storage instead of base64 encoding

### Fixed

- WebSocket reconnection storm when token expires (now uses exponential backoff and auto-logout)
- Mentions and emoji picker dropdowns appearing at bottom of editor instead of near cursor

## [0.7.3] - 2026-01-12

### Added

- Rate limiting on all API endpoints (100 requests/minute default)
- Aggressive rate limiting on sensitive auth endpoints (5 requests/15 minutes)
- Rate limiting on OIDC endpoints (login: 20/minute, callback: 5/15 minutes)
- `BEHIND_PROXY` setting to safely trust X-Forwarded-For headers behind reverse proxies

## [0.7.2] - 2026-01-12

### Added

- Version dialog shows last 5 versions with scrolling
- "View all changes" button linking to GitHub CHANGELOG.md
- Changelog endpoint limit parameter (max 10 versions)

### Fixed

- Dialog scrolling with proper flex layout and 80vh height

## [0.7.1] - 2026-01-12

### Fixed

- Changelog not displaying in Docker deployments
- Changelog file now correctly copied into Docker image
- Fixed path resolution for changelog endpoint in Docker environment

## [0.7.0] - 2026-01-12

### Added

- Multiselect filters for task pages
- Users can now select multiple assignees, statuses, priorities, guilds, and initiatives simultaneously
- "Select all" and "Clear all" options in filter dropdowns
- Dropdown shows selected count (e.g., "3 selected")
- Backend now supports array parameters for all task filters using OR logic
- Changelog display in update dialog when new version is available
- Version dialog showing current version, latest version, and full changelog

### Changed

- Default My Tasks status filter now shows backlog, todo, and in_progress (excludes done by default)
- Task filtering moved to server-side for better performance
- Filters use OR logic within each filter type, AND logic between filter types
- Version number interaction changed from hovercard to dialog for both desktop and mobile
- Version dialog now displays full changelog for current version with parsed sections

### Fixed

- Task filters now correctly apply on backend instead of returning all tasks
- TypeScript type error in task query params

## [0.6.4] - 2026-01-11

### Added

- Template selection dropdown for document creation
- "Save as template" toggle when creating documents

### Fixed

- Project documents section now updates properly after attaching/detaching documents
- Cache invalidation issue causing stale document lists

## [0.6.3] - 2026-01-10

### Added

- Initiative collapsed state persistence to localStorage
- Single localStorage key for all initiative states to reduce clutter

### Changed

- Frontend now served by FastAPI instead of nginx for simpler deployment

### Fixed

- TaskAssigneeList component to work with correct TaskAssignee type
- My Tasks page crash from non-array query data

## [0.6.2] - 2026-01-09

### Changed

- Optimized task list endpoints to reduce payload size
- Moved task filtering to backend for better performance

### Fixed

- Backend test suite - 136/142 tests passing (95.8%)
- Task endpoint validation issues
- Test schema mismatches

## [0.6.1] - 2026-01-08

### Fixed

- Double scrollbar issue on ProjectTabsBar
- Improved scrolling aesthetics on Chromium browsers

## [0.6.0] - 2026-01-07

### Added

- User statistics page with metrics and visualizations
- Chart components for data visualization
- Activity tracking and reporting

## [0.5.3] - 2026-01-06

### Fixed

- PWA manifest for Chrome install prompt
- ScrollArea component on tabs bar for better UX

### Added

- Automated release CI workflow

---

## Version Format

Version numbers follow semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes, incompatible API changes
- **MINOR**: New features, backward-compatible additions
- **PATCH**: Bug fixes, backward-compatible fixes

## Categories

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be-removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security fixes
