# OneBD email delivery

**Production configuration audit:** 2026-07-14

OneBD can send password-reset links, scheduled daily/weekly intelligence
digests, alert notifications, and an operator test message through either
SendGrid or SMTP. At the time of this audit, the production OneBD services did
not have either provider configured, so outbound delivery remains disabled
until the owner supplies a credential in Dokploy.

No provider secret belongs in this repository. Configure the same variables on
both the API and process-worker services through the Dokploy environment, then
redeploy them.

## Provider configuration

SendGrid is selected when `SENDGRID_API_KEY` is present:

```text
SENDGRID_API_KEY=<secret>
DIGEST_FROM_EMAIL=bd-intelligence@pchomelab.com
DIGEST_FROM_NAME=BD Intelligence
APP_URL=https://onebd.pchomelab.com
```

SMTP is selected when SendGrid is absent and `SMTP_HOST` is present:

```text
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=<username>
SMTP_PASS=<secret>
SMTP_SECURITY=starttls
DIGEST_FROM_EMAIL=bd-intelligence@pchomelab.com
DIGEST_FROM_NAME=BD Intelligence
APP_URL=https://onebd.pchomelab.com
```

`SMTP_SECURITY` accepts `starttls`, `ssl`, or `none`; use `none` only for a
trusted internal relay. `EMAIL_TIMEOUT_SECONDS` defaults to 20. If both
providers are configured, SendGrid takes priority.

The configured from-address must be authorized by the selected provider. The
`APP_URL` value is used to build password-reset links and application links in
messages.

## Verification

After redeployment:

1. Sign in and open **Settings**.
2. Confirm that Email Delivery identifies the intended provider.
3. Select **Send test** and confirm receipt at the signed-in user's configured
   digest address (or login email when no override is set).
4. Enable a digest preference and verify that the process worker completes its
   next scheduled daily or weekly run without delivery errors.

`GET /api/settings/email-delivery` reports readiness, provider, from-address,
application URL, and SMTP security mode to an authenticated user. It never
returns API keys, SMTP usernames, or passwords. `POST /api/settings/email-test`
sends only to that user's own configured recipient, rather than accepting an
arbitrary destination.

## Security and failure behavior

- Password-reset tokens are single-use, expire after one hour, invalidate older
  links, and are rate-limited to one new link per minute per account.
- Reset tokens are sent after the database transaction closes and are never
  written to application logs.
- Forgot-password responses do not reveal whether an account exists.
- Disabled users are excluded from password reset and scheduled delivery.
- HTML content derived from source records is escaped before delivery.
- An unconfigured provider fails closed and records a diagnostic warning; no
  message is presented as sent.

Provider selection is an owner-controlled operational setting. It is independent
of the data-access and license-policy controls documented in
`docs/data-inventory-and-access.md`.
