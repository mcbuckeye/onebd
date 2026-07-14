# Accounts and team collaboration

OneBD requires a signed-in user for personal workspaces and team collaboration.
Administrators create, edit, and disable user accounts from **Admin → Users**;
self-registration remains controlled independently by the owner data-access
policy.

## Account boundaries

- JWTs expire after 24 hours, and every authenticated request also checks the
  current database record. Disabling a user or changing a role therefore takes
  effect immediately rather than waiting for an old token to expire.
- Watchlists, deal notes, saved searches, notifications, and conversations use
  the authenticated account ID. Callers cannot select another user's workspace
  with a query parameter.
- The final active administrator cannot remove their own admin role, and an
  administrator cannot disable their own account.

## Team workspaces

The **Teams** page provides shared workspaces with three roles:

- `owner`: controls membership and the team; can remove any shared item or
  comment.
- `editor`: can share evidence and comment.
- `viewer`: can read shared evidence and participate in discussion.

Owners add colleagues by the email address of an existing OneBD account. A
shared item records a typed resource (`deal`, `company`, `drug`, `filing`,
`contract`, `search`, `briefing`, or `other`), optional OneBD/source URL,
record ID, contextual note, creator, and timestamp. Discussions stay attached
to the shared item.

## Owner-controlled data policy

Account and collaboration boundaries protect private user/team state. They do
not override the separate owner-controlled data-access policy documented in
[`data-inventory-and-access.md`](data-inventory-and-access.md): the owner can
choose open, signed-in, or API-key access; enable or disable scope enforcement;
protect or leave open the legacy data API; and enable or disable datasets.
License labels remain advisory metadata and do not silently turn enforcement on.
