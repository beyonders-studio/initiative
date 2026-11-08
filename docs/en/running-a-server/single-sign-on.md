---
icon: lucide/key-square
---

# Single sign-on (OIDC)

Single sign-on lets people into Initiative with an account they already have: the work one, a Google one, or the passkey service somebody runs on a box under the stairs. Initiative speaks OpenID Connect, which nearly every identity provider speaks too. Everything here lives in **Settings → Platform → Authentication**, and only an [owner](platform-roles.md) can open it.

Add as many providers as you like. Each one gets its own button on the sign-in page, and somebody who uses two of them still has one account.

!!! info "Set `APP_URL` before you start"
    A sign-in sends the browser to your provider and catches it on the way back, so Initiative has to know its own public address. Every callback URL on this page is built from `APP_URL`, which defaults to `http://localhost:5173`. Set it and restart before you copy a callback anywhere, or your provider will dutifully send everybody to localhost. See [Configuration](configuration.md).

## Ways in

**Ways in**, at the top of the page, says how a session may start on this server. Each box saves the moment you tick it.

| Way in | Stored as | What it covers | On a new install |
|---|---|---|---|
| **Password** | `password` | An email address and a password held here: the sign-in form, registration and password reset. | On |
| **Single sign-on** | `sso` | Every provider on this page, on the sign-in page and wherever a community connects to one. Each provider's own **Enabled** switch applies on top. | On |
| **Passkey** | `passkey` | A key held by a device or a password manager. People add their own. | On |
| **Email OTP** | `email_otp` | A six-digit code sent to the address somebody types. See [Codes by email](#codes-by-email). | Off |

The authenticator app (`totp`) can't start a session by itself, so it isn't on this list. It's offered under **Settings → Platform → Security → Two-factor authentication**, beside the rule saying who has to hold a second factor (see [Requiring two-factor authentication](configuration.md#requiring-two-factor-authentication)).

The server holds these rules whatever the page shows:

- At least one of the four stays on. The last one ticked can't be unticked.
- Unticking a way that some accounts use alone shows how many there are, and asks you to confirm that number. Those accounts can't sign in until they have another way. Nobody is signed out: open sessions run to their normal end, and personal API keys and the phone app keep working.
- You can't untick the only way your own account signs in. Give your account another way first.
- **Single sign-on** stays on while any community requires its members to arrive through a provider. The page says how many communities are in the way, and each lifts its requirement under its own **Settings → Security**.
- **Email OTP** can't be ticked until [email](email.md) works.
- **Passkey** can't be unticked while it's the only second factor on offer and the server requires one.

??? techspec "Seeding the ways in from the environment"
    `AUTH_LOGIN_METHODS` sets the ways in on a fresh install's first boot and is ignored after that. It takes `password`, `sso`, `totp`, `passkey` and `email_otp`, separated by commas or spaces, in any case. Unset or blank gives `password`, `sso`, `totp` and `passkey`. A value this version doesn't know is dropped with a warning in the log, and `email_otp` is dropped with a warning unless `SMTP_HOST` and `SMTP_FROM_ADDRESS` are both set. Once the database holds a value, this page owns it.

## Codes by email

**Email OTP** signs somebody in with a code sent to their address, with no password, app or key involved. It's the one way in that starts switched off. The others wait for a person to set something up before they do anything, but this one works for every account with an address the moment you tick it.

| | |
|---|---|
| Code | 6 digits |
| Valid for | 10 minutes |
| Wrong tries | 5. The sixth ends the code and they ask for another. |
| Needs | [Email](email.md) configured, or the box refuses to tick. |

The same box takes people without an account. An address nobody holds gets a code, then a prompt for a username, which they have 15 minutes to answer. That's a new account with its address already confirmed. Your sign-up rules still apply: a server that only takes invited people sends a stranger no code.

!!! note "Accounts that never confirmed their address"
    Some accounts sit on an address nobody ever proved, usually from before email was set up. The first time somebody proves that address, with an emailed code or through a provider that vouches for it, the account drops every credential it held before: its password, passkeys, second factor and open sessions. The account keeps its handle, memberships and everything in it, and the person sets up the rest again from their own settings.

## Add a provider

**Add provider** walks you through it in four steps, because a provider is a conversation between two screens. A few values come from your provider, and one has to go back the other way.

1. Select **Add provider**.
2. Pick your provider from the grid. **OpenID Connect**, at the end, is for anything not named there.
3. Fill in the address fields the wizard asks for, then select **Verify**.
4. Select **Next: credentials**.
5. Copy the **Callback URL** and register it with your provider.
6. Paste the **Client ID** and **Client secret** your provider gives you. Leave the secret blank for a public client that uses PKCE alone.
7. Select **Next: how it behaves**.
8. Check the fields below, then select **Connect provider**.

The address is the field people get wrong, so the wizard builds it for you. Pick Keycloak and it asks for your address and your realm separately, then assembles the issuer, so nobody has to type the word `main` into the middle of a URL. **Verify** goes and asks the address for its discovery document. If something answers as the issuer you named, you get a tick and the sign-in, token and key addresses it found. If nothing answers, or something answers for a different issuer, you find out now rather than when the first person tries to sign in. You can't move on until it's happy. A pasted `.well-known/openid-configuration` address works too: Verify trims it back to the issuer.

The callback is `{APP_URL}/api/v1/auth/{slug}/callback`. Your provider refuses the sign-in until that exact address is on its list.

| Field | What to enter | Default |
|---|---|---|
| **Slug** | 1 to 64 characters: lowercase letters, digits and dashes, not starting or ending with a dash. It forms the sign-in and callback URLs, so it can't change once saved. | The preset's, such as `keycloak` or `pocket-id`. Empty for **OpenID Connect**. |
| **Display name** | What the button says, up to 128 characters. "Work account" helps more than "OIDC". | The preset's name. Empty for **OpenID Connect**. |
| **Scopes** | Space-separated, up to 512 characters. Add `offline_access` if you want group changes picked up between sign-ins. | Whichever of `openid`, `email`, `profile`, `offline_access` and `groups` your provider lists, with `openid` always included. `openid email profile` if it lists none. |
| **Groups claim** | Where your provider puts a person's groups in the token: `groups` for most, `realm_access.roles` for Keycloak. Dots reach into nested claims. Only needed for [sorting people into communities](#sorting-people-into-communities). | Empty |
| **Create accounts on first sign-in** | On, a stranger who signs in gets an account, as long as the server takes sign-ups without an invite (**Let anyone sign up** and community creation, both under **Settings → Platform → Community**). Off, the button only works for people who already have an account. | On |
| **Enabled** | Off takes the button away and keeps everything you typed. | On |

The issuer must be an `https://` address. Everything but the slug can be changed later.

The two addresses under **This deployment** belong to every provider at once: the **Post-login redirect** (`{APP_URL}/oidc/callback`), where a sign-in finishes in the web app, and the **Mobile app callback** (`initiative://oidc/callback`). Most providers never ask for either.

## Edit, test or delete a provider

Each provider's row has three buttons.

| Button | What it does |
|---|---|
| **Test** | Asks the saved issuer for its discovery document again, without caching the answer. Handy after somebody reorganized things at the other end. |
| **Edit** | One form with every field, the same **Verify** and the same callback to copy. The secret is write-only: leave it blank to keep the stored one, type a new one to replace it, or tick **Remove the stored secret**. |
| **Delete** | Removes the provider and every link an account has to it. Its placement rules go with it. |

Edit also has **Its word counts for a second factor**. On, a sign-in through this provider answers a requirement for a second factor whenever the provider reports running one: `mfa` in the token's `amr` claim, or `phr` or `phrh` in `amr` or `acr`. The wizard ticks it for Microsoft Entra ID, Okta, Auth0 and Pocket ID, which document reporting it, and leaves it off for the rest. Leave it off unless you know your provider reports this honestly. People signing in through it are then asked for a factor of their own.

Delete refuses, with nothing changed, while the provider is:

- the provider a community connects to, or the one its sign-in requirement names. That community disconnects it or lifts the requirement first.
- the only way some account signs in. Those people set a password or link another provider first.

Everybody else keeps their account and every other way they had of reaching it.

![Platform settings › Authentication](../images/running-a-server/oidc-settings.png)

## Provider quickstarts

Any provider that follows the OpenID Connect standard works. The wizard already knows how each of these spells its issuer, asks for the parts and assembles the address. What's left is the part you do at the other end.

=== "Pocket ID"

    1. Go to **OIDC Clients → Add client** and name it "Initiative".
    2. Set its **Callback URL** to the one the wizard is showing you.
    3. Copy the generated **Client ID** and **Client secret** back in.

    The wizard asks for your Pocket ID **Address**. Pocket ID signs everyone in with a passkey, so your Initiative sign-ins get passkeys with nothing more to do. For group sorting, turn groups on there and pick `groups` as the **Groups claim**.

=== "Authentik"

    1. Create a **Provider → OAuth2/OpenID**, set its **Redirect URI** to the callback URL the wizard is showing you, and note the **Client ID** and **Client secret**.
    2. Create an **Application** and bind the provider to it.

    The wizard asks for your **Address** and the **Application slug**. That's the application's slug, not the provider's, which is the one people mix up. For group sorting, add the `groups` scope there and pick `groups` as the **Groups claim**.

=== "Authelia"

    Authelia is configured in YAML rather than on a screen.

    1. Under `identity_providers.oidc.clients`, add a client with a `client_id`, a **hashed** `client_secret`, `redirect_uris` set to the callback URL the wizard is showing you, and `scopes: [openid, profile, email, groups]`.
    2. Restart Authelia.

    The wizard asks for your Authelia **Address**. The secret you paste back is the plaintext one, not the hash you put in the YAML.

=== "Keycloak"

    1. In your realm, create an OpenID Connect **Client** with **Client authentication** on and a **Valid redirect URI** of the callback URL the wizard is showing you.
    2. The **Client secret** is on the client's **Credentials** tab. The **Client ID** is the client's name.

    The wizard asks for your **Address** and your **Realm** and builds `https://{address}/realms/{realm}` from them. For group sorting, add a groups or roles mapper and pick `groups` or `realm_access.roles` as the **Groups claim**.

=== "Dex"

    1. Add a client under `staticClients` in your Dex config, with an `id`, a `secret`, a `name` and `redirectURIs` set to the callback URL the wizard is showing you.
    2. Restart Dex.

    The wizard asks for your **Address** and builds `https://{address}/dex`. Dex's issuer is whatever its config sets as `issuer`, so if yours isn't mounted at `/dex`, choose **OpenID Connect** instead and type the issuer exactly. For group sorting, add the `groups` scope and pick `groups` as the **Groups claim**.

=== "Salesforce"

    1. Go to **Setup → App Manager → New Connected App** and tick **Enable OAuth Settings**.
    2. Set the **Callback URL** to the one the wizard is showing you, and add the `openid`, `email` and `profile` scopes.
    3. Copy the **Consumer Key** and **Consumer Secret** back in.

    The wizard asks for your **Address**, and which one matters: a sandbox is `test.salesforce.com`, and an org with My Domain signs in at its own address. Use the one your people actually use, not the generic `login.salesforce.com`.

=== "JumpCloud"

    1. Go to **SSO Applications → Add New Application → Custom OIDC App**.
    2. Set the **Redirect URI** to the callback URL the wizard is showing you.
    3. Copy the **Client ID** and **Client Secret** back in, and attach the user groups who should get in.

    There's no address to fill in. JumpCloud's issuer is `https://oauth.id.jumpcloud.com/` for everybody, trailing slash included.

=== "Google, Entra, Okta, Auth0"

    These four work the same way: register an app, add the callback URL the wizard is showing you, and copy the credentials back.

    | Provider | The wizard asks for | Example |
    |---|---|---|
    | **Google** | Nothing. Its issuer is always `https://accounts.google.com`. | |
    | **Microsoft Entra ID** | **Tenant ID** | `00000000-0000-0000-0000-000000000000` |
    | **Okta** | **Okta domain** | `dev-12345.okta.com` |
    | **Auth0** | **Auth0 domain** | `your-tenant.eu.auth0.com` |

=== "Zitadel"

    1. Create a project, then an **Application** of type **Web** using **Code** with PKCE.
    2. Set its redirect URI to the callback URL the wizard is showing you.
    3. Copy the **Client ID** and **Client secret** back in.

    The wizard asks for your **Address**: your own domain, or `your-instance.zitadel.cloud`.

## Letting a community use a provider

The providers are yours, and a community connects to one. You say this server can sign people in with Google. A community then says its members come in through Google, and only the accounts in its own Workspace domain. That second half matters, because Google will vouch for anybody with a Google account.

A community never sees an issuer, a client ID or a secret, and never types an address. A community bringing its own identity provider works the same way with you doing the registering: add their provider on this page when you onboard them, and they connect to it.

Two switches decide what a community may do here. They're yours, per community, under **Operator dashboard → Communities → Manage → What it decides for itself** (operators and owners). Both start off, and neither needs the other.

| Switch | What it lets the community's admins do |
|---|---|
| **Its own sign-in** | Connect to providers you've registered, say which accounts on one count as theirs and where those people land (as a member or an admin, and in an initiative if they like), and require members to arrive that way. It also gives them a member sign-in link that brings people straight into the community. |
| **Its own security standard** | Refuse personal API keys, and make members sign in again every 12 hours. For a community answering to an auditor. |

On their side it's one tab, **Settings → Security**, which leads with **Set up sign-in** while nothing is connected. It asks four questions in the order they depend on each other: **Which way in**, **Whose people**, **Where they land** and **Do we insist**. [Your community's sign-in and security](../security/community-security.md) walks through it.

Withdrawing a switch closes the part of their **Security** tab it governs and nothing else. Their connections stay, their members keep signing in, and a requirement they already set stays in force. Their admins can always lift a requirement, whatever you've granted, so no community gets stuck behind a sign-in nobody can undo.

### What a community inherits

Where this server is one organization (one provider, one tenant, communities that are its teams), you can answer "whose accounts count" once for every community. **What a community inherits**, at the bottom of the Authentication page, takes a claim and the values that count for each provider.

1. Select **Answer for it** beside the provider.
2. Fill in **Which claim decides**, such as `hd` for a Google Workspace domain or `tid` for an Entra tenant.
3. Fill in **Values that count**, separated by commas.
4. Select **Save**.

Every community connecting to that provider then inherits the answer, shown to them as **From your server**, until it gives its own with **Make it ours**. A community's own answer replaces yours outright, and the two are never merged. **Withdraw** takes your answer back.

### Agreeing a community's claim

A community names its own domain or tenant, and Initiative can't tell whether `acme.com` really is theirs. Its connection lets matching people sign in straight away. What waits is joining them to the community on arrival: somebody outside the community has to agree first. Until then, people join by invitation.

The question reaches you in three places, and an answer in any one of them counts everywhere:

| Where | Who answers |
|---|---|
| A support case in your [operations community](operations-community.md), opened when the community saves its values | Whoever works the support project |
| **Operator dashboard → Sign-in placement → Waiting for an answer**, every community's in one list | Operators and owners |
| **Operator dashboard → Communities → Manage → Who it counts as its own**, for one community | Operators and owners |

Each has **Agree**, and **Withdraw** once agreed.

## Sorting people into communities

If your provider already knows who's in which group, Initiative can read that and put people where they belong when they sign in, with no invite and nobody watching an inbox.

First tell Initiative where the provider keeps its groups by setting its **Groups claim**. The rules can then come from either end:

| Who writes them | Where | Suits |
|---|---|---|
| Operators and owners | **Operator dashboard → Sign-in placement** | One identity team deciding where everybody goes, across every community at once. |
| A community with **Its own sign-in** | Its own **Settings → Security** | A community that knows its own groups. See [Where your people land](../security/community-security.md#where-your-people-land). |

Both sets apply together. Somebody matched by rules from both lands at the higher of the two standings, and admin outranks member.

### Rules on a provider

Each rule says that people in a group land in a community as a member or an admin, and optionally in one of its initiatives with a role.

1. Open **Operator dashboard → Sign-in placement**.
2. Select **Add rule** under the provider.
3. Type the **Group** as your provider reports it. Leave it empty to place everybody from one directory (see [below](#one-provider-several-directories)).
4. Choose the **Community**, then the standing people get there.
5. Optionally choose an initiative and a role in it. The community's initiatives appear once it takes this provider's rules.
6. Select **Save rule**.

A rule places people only in a community that agreed to take this provider's rules, and there are two ways to agree:

- **The community agrees** by switching on **Let your server place people** on its connection. This suits a server shared by separate organizations.
- **An owner agrees for everybody** with **Apply placement rules to every community**, at the top of the page. This suits a server that is one organization, where asking two hundred teams to tick a box would take a month of follow-up emails. Every change to this switch is written to the [audit log](configuration.md#logs).

A rule for a community that hasn't agreed is kept, marked **Not applying**, and starts working the moment it does. In the community picker it shows as **Not accepted**. Communities always see the rules that place people in them, listed on their Security tab as coming from your server.

Deleting a rule stops it placing anybody. What it gave people is taken back the next time they sign in through that provider.

### One provider, several directories

A bridge such as Keycloak or Authentik, standing in front of other identity providers, signs in people from several directories through one provider. It's also how a directory that only speaks SAML reaches Initiative. Two of those directories can each have a group called `staff` that means entirely different people.

So a rule can also name a directory, under **Only people from one directory**: a **Claim** the bridge adds to its tokens, and this directory's **Value**, such as `idp` = `acme-adfs`. The rule then matches only people from there. Name a directory and leave the group empty, and the rule places everybody arriving from that directory. A rule that names only a directory works even before the provider has a **Groups claim**.

??? techspec "How placement is evaluated"
    On each sign-in, Initiative reads the provider's **Groups claim** path from the userinfo response, falling back to the ID token. A string or a list of strings is accepted, and values are compared in lower case, so `Staff` matches a rule for `staff`.

    A community's own rule applies where its connection, or your inherited answer where it has none, admits the person's claims. A rule on the provider applies where the community accepted provider rules or they apply everywhere, and, if it names a directory, where that claim carries that value. Each community gets the highest standing any matching rule gives.

    Reconciliation is scoped to the provider being signed in through. It grants what that provider's rules match, and takes back only memberships that the same provider's earlier reconciliations created. A membership somebody was invited to is never touched.

    Group changes land without a fresh sign-in where the provider hands out refresh tokens (the `offline_access` scope) and has a client secret. A background sweep runs every 300 seconds and refreshes each linked account at most once every 15 minutes, for every enabled provider that has a **Groups claim** or a directory-only rule. A provider without a userinfo endpoint is skipped.

## Set up the first provider from the environment

The `OIDC_*` variables create one provider on a fresh install's first boot, which suits a deployment that's scripted end to end. They do nothing once that provider exists: from then on it's a row on the Authentication page like any other, and rotating its secret means pasting the new one there.

| Variable | What it sets | Default |
|---|---|---|
| `OIDC_ENABLED` | **Enabled** | `false` |
| `OIDC_ISSUER` | The issuer address. Required for the seed. | Unset |
| `OIDC_CLIENT_ID` | **Client ID**. Required for the seed. | Unset |
| `OIDC_CLIENT_SECRET` | **Client secret**. Stored encrypted. | Unset |
| `OIDC_PROVIDER_NAME` | **Display name** | `SSO` |
| `OIDC_SCOPES` | **Scopes**, comma- or space-separated. Blank means the default. | `openid profile email offline_access` |

The provider it creates has the slug `oidc`, so its callback is `{APP_URL}/api/v1/auth/oidc/callback`, and **Create accounts on first sign-in** is on. Unlike any other provider, the `oidc` one needs a stored client secret before its button works.

??? techspec "What a sign-in checks"
    - The issuer, and every address its discovery document names, must be `https`. Each request to the provider times out after 10 seconds and reads at most 512 KiB.
    - The discovery document is cached for 3,600 seconds and the signing keys for 300 seconds. A token signed with an unknown key ID refetches the keys once. **Test** and **Verify** never use or fill the cache.
    - Every sign-in uses PKCE and a nonce. The round trip through the provider must finish within 600 seconds.
    - The ID token must be signed with an asymmetric algorithm: RS256, RS384, RS512, PS256, PS384, PS512, ES256, ES384, ES512 or EdDSA, narrowed to what the provider advertises. A provider that advertises none is held to RS256 and ES256. `iss`, `sub`, `aud`, `exp` and `iat` are required, with 60 seconds of clock skew allowed.
    - A first sign-in links to an existing account by email address only when the provider sends `email_verified` as `true`. A missing or false `email_verified` that matches an existing account is refused.
    - Client secrets and refresh tokens are encrypted at rest with keys derived from `SECRET_KEY`.

## Related

- [Configuration](configuration.md) for `APP_URL` and the other settings.
- [Platform roles](platform-roles.md) for who can do what on this page.
- [Your community's sign-in and security](../security/community-security.md) for the community's side.
- [Signing in](../getting-started/signing-in.md) for what people see.
