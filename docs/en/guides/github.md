---
icon: lucide/git-pull-request
---

# GitHub

The GitHub plug-in ties your tasks to the code that does them. Name a task in a branch, and the branch and its pull request turn up on the task, with whether the pull request is reviewed, whether its checks pass and whether it merged. Nobody has to paste a link into a comment, and nobody has to ask in standup whether that fix ever shipped.

It also brings a GitHub organization's issues and pull requests onto your dashboards, and tells automations when an issue opens or closes, a review is requested, or a release, a pre-release or a tag goes out.

It's an [integration](plugins-and-marketplace.md#kinds-of-plug-in): Initiative does all the talking to GitHub, and nothing extra runs on your server. Whoever runs the server sets it up once, first; see [Running plug-ins](../running-a-server/plugins.md#a-plug-in-that-runs-inside-initiative).

## Add GitHub to your community

This is the community's [superadmin](running-a-community.md#why-superadmin-is-separate)'s job, and it takes a GitHub account that owns the organization (or an owner willing to approve it).

1. Select **Add a plug-in** at the bottom of the **Plug-ins** section in the sidebar.
2. Open **GitHub**.
3. Select **Add to community**, decide [what it can reach and where it works](plugins-and-marketplace.md#what-youre-agreeing-to), and select **Add to community** again.
4. Open the plug-in's settings (the gear beside its name in the sidebar).
5. Under **Community credential**, select **Connect** on **GitHub organization**.
6. On GitHub, choose the account and the repositories the plug-in may see, and confirm.
7. Authorize once more when GitHub asks.

You land back in Initiative, connected. Only an owner of the account on GitHub can finish step 6; anybody else sends the owner a request, and Initiative says it's waiting until they approve.

Adding or removing repositories later happens on GitHub, on the GitHub App's **Configure** page, with nothing to change in Initiative.

## Connect your own GitHub account

The organization's connection covers reading: dashboard tiles and task links answer the same for everyone. Anything done *in your name* needs your own account, which is starting a branch, your own review queue and pull requests, and anything an automation of yours writes to GitHub.

Connect **Your GitHub account** the way you'd [connect any account to a plug-in](plugins-and-marketplace.md#connect-your-own-account-to-a-plug-in). Disconnecting ends the authorization on GitHub's side too, so there's nothing to clean up there.

## Link a task to a branch or a pull request

Every task has a **reference**: your community's prefix and the task's number, like `acme-42`. The task's **GitHub** section shows its own.

Put the reference in a branch's name (`acme-42-fix-sign-in`, `feature/ACME-42`) and the branch links to the task when it's pushed. A pull request links when its branch, title or description holds the reference. That's checked when it opens and on every push, merge or reopen after, so work started before anybody added the plug-in links on its next change.

Case doesn't matter, but the reference has to be a word of its own: `[acme-42]` links to task 42, `xacme-42` links to nothing, and `acme-420` is task 420.

### Start a branch from a task

You need your own GitHub account connected.

1. Open the task.
2. In its **GitHub** section, select **Start a branch**.
3. Pick the repository and the branch to start from.
4. Select **Start a branch**.

GitHub gets a new branch named after the task, created by you, and the task lists it straight away.

### Link a pull request by hand

For a pull request that never mentioned the task:

1. Open the task.
2. In its **GitHub** section, select **Link a pull request**.
3. Pick the repository and type the pull request's number.
4. Select **Link a pull request**.

### Unlink a branch or a pull request

Select **Unlink** beside it in the task's **GitHub** section. If GitHub still names the task (in the branch name, say), the link comes back on the pull request's next push, merge or reopen, so take the reference out on GitHub to unlink it for good.

## See where a pull request stands

Each linked pull request on a task shows three things:

| | Shows |
|---|---|
| **Status** | Draft, open, merged or closed |
| **Review** | Approved, changes requested, review required, or no review |
| **Checks** | Passing, failing, pending, or none |

Most changes arrive the moment GitHub sends them. The plug-in also looks over the organization's recently changed pull requests every 15 minutes, so checks settle within about that, and anything that went missing on the way catches up. A branch deleted on GitHub shows as deleted.

The **Pull requests** and **Branches** fields can go on a task's page without the rest of the section. Whoever looks after the project's [layouts](layouts.md) places them, and who sees any of it is the **Use GitHub** permission on the initiative's [Roles screen](../sharing/initiative-roles.md#plug-ins-on-a-role), which every role starts with.

## Change the task reference prefix

The prefix starts as your community's name, cut down to letters and digits. No other community on the server can have the same one. Changing it is the superadmin's job.

1. Open the plug-in's settings.
2. Under **Settings**, change **Task reference prefix**.

References made with an earlier prefix keep linking, so nothing on GitHub needs renaming.

## Put GitHub on a dashboard

The plug-in brings these [widgets](dashboards.md#read-a-plug-ins-data), and a ready-made **GitHub overview** dashboard that arranges four of them. You point each tile at a repository where you place it.

| Widget | Shows |
|---|---|
| **Open issues** | A repository's open issues |
| **Waiting on you** | Pull requests waiting on your review |
| **Your review requests** | Reviews you've been asked for |
| **Your pull requests** | The pull requests you opened |
| **Linked pull requests** | The organization's open pull requests that name a task, with each task they name |
| **Dependabot alerts** | Alerts by severity |
| **Issues opened and closed** | A fortnight of issues opened against issues closed |

**Waiting on you**, **Your review requests** and **Your pull requests** read GitHub as you, so they need your own account connected. **Your review requests** and **Your pull requests** show yours from anywhere the GitHub App is installed, even in a community that hasn't connected an organization. Everything else reads as the organization, and shows everybody the same thing.

## Let automations act on GitHub

The plug-in tells automations when an issue is opened or closed, when a review is requested, and when a release is published, a pre-release is published or a tag is pushed, so an automation can start from any of them. An automation can also move a task when its linked pull request merges.

What an automation writes to GitHub (a comment, a label, a closed issue) is written as the person whose automation it is, from their own account, or as the organization when the automation acts for the whole community. Starting a branch is always a person's own.
