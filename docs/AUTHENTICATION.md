# Authentication

This document describes all authentication methods currently implemented in this build:

- Email/password login (existing flow)
- Social OAuth signup/login (default provider: Google)
- ORCID OAuth signup/login

Both OAuth flows auto-create users with default role `researcher`.

## Overview

### Existing login

- Route: `POST /login`
- Authenticates against `admin_users` by email/password.
- Role behavior:
  - `admin`, `researcher`: redirected to `/admin/dashboard`
  - `user`: redirected to experiment selection flow

### New social OAuth login/signup

- Start route: `GET /login/social`
- Callback route: `GET /login/social/callback`
- Provider defaults to Google OpenID Connect endpoints.
- On first login:
  - account is created in `admin_users`
  - role is set to `researcher`
- On subsequent logins:
  - existing account is resolved by email

### New ORCID OAuth login/signup

- Start route: `GET /login/orcid`
- Callback route: `GET /login/orcid/callback`
- Uses ORCID OAuth authorization code flow.
- On first login:
  - account is created in `admin_users`
  - role is set to `researcher`
- On subsequent logins:
  - existing account is resolved by derived ORCID identity email

## Environment Variables

Configure these in your environment before starting YSocial.

### Social OAuth (Google by default)

- `SOCIAL_PROVIDER` (default: `google`)
- `SOCIAL_CLIENT_ID` (or `GOOGLE_CLIENT_ID`)
- `SOCIAL_CLIENT_SECRET` (or `GOOGLE_CLIENT_SECRET`)
- `SOCIAL_AUTH_URL` (default Google auth endpoint)
- `SOCIAL_TOKEN_URL` (default Google token endpoint)
- `SOCIAL_USERINFO_URL` (default Google userinfo endpoint)

If `SOCIAL_CLIENT_ID` and `SOCIAL_CLIENT_SECRET` are not set, social login is disabled and the UI flow will show an error flash.

### ORCID OAuth

- `ORCID_CLIENT_ID` (required for ORCID flow)
- `ORCID_CLIENT_SECRET` (required for ORCID flow)
- `ORCID_BASE_URL` (default: `https://orcid.org`)

If ORCID client values are not set, ORCID login is disabled and the UI flow will show an error flash.

## Google Setup Example

Add the callback URL below in your Google OAuth app:

- `http://localhost:8080/login/social/callback`

Example environment:

```bash
export SOCIAL_PROVIDER=google
export SOCIAL_CLIENT_ID="your-google-client-id"
export SOCIAL_CLIENT_SECRET="your-google-client-secret"
```

## ORCID Setup Example

Add the callback URL below in your ORCID application settings:

- `http://localhost:8080/login/orcid/callback`

Example environment:

```bash
export ORCID_CLIENT_ID="your-orcid-client-id"
export ORCID_CLIENT_SECRET="your-orcid-client-secret"
export ORCID_BASE_URL="https://orcid.org"
```

For ORCID sandbox testing:

```bash
export ORCID_BASE_URL="https://sandbox.orcid.org"
```

## UI Integration

The login page now includes two additional buttons:

- `Continue with Social Account`
- `Continue with ORCID`

These are integrated into:

- `y_web/templates/login.html`

## Data Model and Account Provisioning

New OAuth users are stored in `admin_users` with:

- `role="researcher"` (default)
- generated secure password hash (unused for OAuth login but required by schema)
- unique username auto-generated from provider display name

### ORCID identity mapping

ORCID does not always return email in token responses. This implementation maps ORCID identities using:

- `orcid+<orcid-id>@orcid.local`

This keeps logins stable and idempotent per ORCID identifier.

## Security Notes

- OAuth flows use random `state` values stored in session to mitigate CSRF.
- Callback state is validated and consumed once.
- Network calls to token/userinfo endpoints use request timeouts.

## Troubleshooting

### "Social login is not configured."

Set `SOCIAL_CLIENT_ID` and `SOCIAL_CLIENT_SECRET` (or Google aliases).

### "ORCID login is not configured."

Set `ORCID_CLIENT_ID` and `ORCID_CLIENT_SECRET`.

### "Invalid ... login response."

Usually indicates callback mismatch, expired session, or state mismatch.
Check:

- callback URL in provider console exactly matches the app callback route
- app host/port matches registered callback
- browser session/cookies are enabled

### Provider returned no email (social login)

Provider account scopes must include profile/email (`openid email profile` for Google).

## Source Files

- `y_web/auth.py` (OAuth routes and account provisioning)
- `y_web/__init__.py` (OAuth config wiring)
- `y_web/templates/login.html` (buttons/UI integration)
