---
icon: lucide/megaphone
---

# Reporting a problem

If something about security doesn't look right, please tell somebody. Where the report goes depends on what it's about:

| What you found | Who to tell |
|---|---|
| Something you can see that you think you shouldn't, or a weakness in the server you use | Whoever runs that server, with **Report a security problem** |
| An email saying your account changed, when you didn't change it | Whoever runs that server, with **This wasn't me** in the email |
| A comment, post, picture or profile that shouldn't be there | The people who look after it, with **Report** |
| A flaw in the Initiative software itself, which every server running it would have | The Initiative project, privately by email |

Whichever it is, don't look further than you need to confirm it, and don't share what you saw.

## Something you can see that you shouldn't

If you come across content you don't think you should have access to, such as another community's content or a project that wasn't shared with you, report it. It might be a setting, or it might be a bug. A community admin can check the community's sharing, and whoever runs the server can look into the rest.

## A problem with the server you use

To tell whoever runs your server about a security problem:

1. Select **Report a security problem**. It's under **My Settings → Security**, in **My Tickets**, and in the command palette.
2. Under **What is it about?**, choose **A weakness in this server**, **Someone else got into my account** or **Something else**.
3. Under **What did you find?**, say what you saw, where, and how to see it again. Attach a screenshot if it helps.
4. Select **Send report**.

The people who run the server read it, and you follow it and talk with them about it in **My Tickets**. Where the server doesn't take these reports in the app, **Report a security problem** shows the address to write to.

From outside, a server says where to send security reports at `/.well-known/security.txt`. That file names its security contact and, where the server takes reports in the app, the form.

## An account change you didn't make

Every email about a change to how your account signs in has a **This wasn't me** button. Choosing it signs your account out on every browser and device, turns off your API keys, and tells the people who run the server. Where nobody is set up to hear it, the page says who to tell. See [Profile & preferences](../account/profile-and-preferences.md).

## Content that shouldn't be there

For something somebody posted, such as a comment, a post, a picture or a profile, use **Report** on it. A report about something in a community goes to that community's moderators. A report about an account goes to whoever runs the server. A report that cites a law goes to both.

## A vulnerability in Initiative

A flaw in the Initiative software itself goes to the project, privately, so it can be fixed before it's made public. If you run a server and receive a report about the software, forward it there.

!!! warning "Please don't open a public issue for a security problem"
    Public issues are visible to everyone. Use the email address below.

Email **<security@beyonders.studio>** with:

- a description of the problem
- steps to reproduce it
- what it could affect
- a suggested fix, if you have one

The project will:

- acknowledge your report within 48 hours
- give an estimated timeline for a fix
- tell you when it's resolved
- credit you in the release notes, unless you'd rather stay anonymous

Fixes go into the latest release, so that's the version to run.

### What's covered

- the service behind the app (`backend/`)
- the web app, and the phone and desktop apps built from it (`frontend/`)
- the Docker configuration and deployment scripts
- the project's GitHub Actions workflows

Vulnerabilities in third-party dependencies are out of scope, but a heads-up about a vulnerable dependency is welcome.

### Testing responsibly

Test against a server you run. Probing a server you don't own or administer, without its owner's permission, isn't acceptable, whatever the intention.

## Related

- [How your data is kept separate](how-your-data-is-kept-separate.md): what the boundaries are.
- [Security & privacy](index.md): the short version.
