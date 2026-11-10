# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under a `## After <release>` heading naming the
release it breaks from. Once the next release ships, its entries no longer
matter and can be deleted.

## After 0.78.0

### Every message device signs its keys

A device registered before 0.73 signed itself later through its own route;
those that never did are removed, so the route goes and a registration, and
every key it publishes, carries its signature.

- POST /api/v1/me/dm/devices the request property `fallback_key/signature` became required
- POST /api/v1/me/dm/devices the request property `one_time_keys/items/signature` became required
- POST /api/v1/me/dm/devices the request property `signature` became required
- POST /api/v1/me/dm/devices request property `fallback_key/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices request property `one_time_keys/items/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices request property `signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/devices the `fallback_key/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `one_time_keys/items/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/devices the `fallback_key/signature` request property's minLength was set to `1`
- POST /api/v1/me/dm/devices the `one_time_keys/items/signature` request property's minLength was set to `1`
- POST /api/v1/me/dm/devices the `signature` request property's minLength was set to `1`
- PUT /api/v1/me/dm/devices/{device_id}/signature api path removed without deprecation
- POST /api/v1/me/dm/one-time-keys the request property `one_time_keys/items/signature` became required
- POST /api/v1/me/dm/one-time-keys request property `one_time_keys/items/signature` list-of-types was narrowed by removing types `null` from media type `application/json`
- POST /api/v1/me/dm/one-time-keys the `one_time_keys/items/signature` request property's maxLength was set to `88`
- POST /api/v1/me/dm/one-time-keys the `one_time_keys/items/signature` request property's minLength was set to `1`

### An account's email address as it is stored

The backend's type cleanup reads an account's `email` as the string it is
stored as rather than validating it as an address on the way out, so a read's
`email` no longer carries `format: email`. The operator's user reads say an
account with no address has `null` rather than `""`, as every other read of an
account already does.

- POST /api/v1/auth/register the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `201`
- GET /api/v1/me the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PATCH /api/v1/me the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- POST /api/v1/me/age-confirmation the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PUT /api/v1/me/avatar the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- POST /api/v1/me/legal-acceptance the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- PATCH /api/v1/me/username the `email/anyOf[subschema #1]/` response's property `format` changed from `email` to `none` for status `200`
- GET /api/v1/operator/users response property `items/items/email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/age-block response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/reactivate response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/restore response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/sessions response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- POST /api/v1/operator/users/{user_id}/suspension response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`
- PATCH /api/v1/operator/users/{user_id}/username response property `email` list-of-types was widened by adding types `null` to media type `application/json` of response `200`

### Announcements in notifications

`NotificationType` takes `announcement`: a dismissed announcement leaves a
read line in the reader's notifications, so every response carrying a
notification's type may hold it.

- GET /api/v1/notifications/ added the new `announcement` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `announcement` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `announcement` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `announcement` enum value to the `type` response property for the response status `200`

### The Ideas board

`IntakeStream` takes `ideas`: Initiative Cloud's Ideas board is a stream the
team fills by hand, so every response carrying a case's or a binding's stream
may hold it. `NotificationType` takes `idea_updated`: a voter is told when an
idea moves, so every response carrying a notification's type may hold it.

- GET /api/v1/access-grants/cases added the new `ideas` enum value to the `items/items/stream` response property for the response status `200`
- GET /api/v1/c/{community_id}/tasks/{task_id}/case added the new `ideas` enum value to the `stream` response property for the response status `200`
- GET /api/v1/me/tickets added the new `ideas` enum value to the `items/items/stream` response property for the response status `200`
- GET /api/v1/me/tickets/{task_id} added the new `ideas` enum value to the `stream` response property for the response status `200`
- POST /api/v1/me/tickets/{task_id}/replies added the new `ideas` enum value to the `stream` response property for the response status `201`
- GET /api/v1/operator/users/{user_id}/cases added the new `ideas` enum value to the `items/stream` response property for the response status `200`
- GET /api/v1/settings/intake added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- GET /api/v1/settings/intake added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/community added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/community added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/contact added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/contact added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream} added the new `ideas` enum value to the `stream` response property for the response status `200`
- POST /api/v1/settings/intake/{stream}/blueprint added the new `ideas` enum value to the `stream` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream}/contact added the new `ideas` enum value to the `bindings/items/stream` response property for the response status `200`
- PUT /api/v1/settings/intake/{stream}/contact added the new `ideas` enum value to the `contact_emails/propertyNames/` response property for the response status `200`
- GET /api/v1/notifications/ added the new `idea_updated` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `idea_updated` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `idea_updated` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `idea_updated` enum value to the `type` response property for the response status `200`

### Feedback to Initiative Cloud

`TicketMode` takes `cloud`: Initiative Cloud takes the stream, and people
send it there, signed in to Cloud, as feedback is from any server. Every
stream's `mode` in the ticket availability may hold it.

- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `feedback/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `moderation/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `security/mode` response property for the response status `200`
- GET /api/v1/me/tickets/availability added the new `cloud` enum value to the `support/mode` response property for the response status `200`

### Communities that take requests to join

A community's `is_community` becomes `join_policy` (`private`, `request` or
`open`), and `NotificationType` takes the three notices of a request to join a
community, so every response carrying a notification's type may hold them.

- GET /api/v1/communities/ removed the required property `items/is_community` from the response with the `200` status
- POST /api/v1/communities/ removed the required property `is_community` from the response with the `201` status
- POST /api/v1/communities/directory/{community_id}/join removed the required property `is_community` from the response with the `200` status
- POST /api/v1/communities/invite/accept removed the required property `is_community` from the response with the `200` status
- GET /api/v1/communities/{community_id} removed the required property `is_community` from the response with the `200` status
- PATCH /api/v1/communities/{community_id} removed the required property `is_community` from the response with the `200` status
- DELETE /api/v1/communities/{community_id}/banner removed the required property `is_community` from the response with the `200` status
- PUT /api/v1/communities/{community_id}/banner removed the required property `is_community` from the response with the `200` status
- DELETE /api/v1/communities/{community_id}/icon removed the required property `is_community` from the response with the `200` status
- PUT /api/v1/communities/{community_id}/icon removed the required property `is_community` from the response with the `200` status
- GET /api/v1/notifications/ added the new `community_join_approved` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/ added the new `community_join_denied` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/ added the new `community_join_requested` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_approved` enum value to the `notification/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_denied` enum value to the `notification/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_join_requested` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_approved` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_denied` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_join_requested` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_approved` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_denied` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_join_requested` enum value to the `type` response property for the response status `200`
