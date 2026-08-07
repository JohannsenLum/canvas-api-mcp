# Security Policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Report it privately through
GitHub's [Security Advisories](https://github.com/JohannsenLum/canvas-api-mcp/security/advisories/new)
on this repository, which creates a private thread only maintainers can see.

Please include what you were doing, what happened, and — if it involves credential
exposure — whether a real Canvas token was affected, so it can be revoked quickly.

This is a personal project, not a funded one. Expect a first response within about a
week. There is no bounty.

## What counts as a vulnerability here

This server holds a Canvas access token, which is **password-equivalent**: it can read
grades, submissions, and private instructor messages, and can submit work as the user.
Anything that could leak or misuse that token is the highest-severity class of bug.

Specifically in scope:

- **Token leakage.** The token appearing in logs, error messages, tracebacks, tool
  results, cached files, or being sent to any host other than the user's own Canvas
  instance.
- **Sending the token to a third party.** `read_file` downloads Canvas files from a
  pre-signed URL on a *different* host. It deliberately uses a bare HTTP client with
  no `Authorization` header. Any change that reuses the authenticated client for that
  download is a security bug, not a refactor.
- **Unintended writes.** Anything that causes `submit_assignment`,
  `post_discussion_reply`, or a non-GET `canvas_request` to fire without the user
  seeing an approval prompt, or that misrepresents a write tool as read-only in its
  annotations.
- **Rate-limit bypass.** The throttling in `client.py` is a compliance requirement of
  Canvas's API Policy. Removing or circumventing it can get a user's account
  restricted.

Out of scope:

- Canvas returning 401/403. That is Canvas enforcing permissions correctly.
- Your institution disabling student token creation. Not something this project can
  change.
- Vulnerabilities in Canvas itself — report those to Instructure.

## For users

- **Set an expiry** when you create a token. A token with no expiry is valid forever if
  it leaks.
- **Revoke immediately** if you suspect exposure: Canvas → Account → Settings →
  Approved Integrations → the bin icon. Revocation is instant and affects only that
  token.
- **Never commit your token.** `.env` and `.env.local` are gitignored. Your token
  belongs in your MCP client's config, which lives outside this repository.
- **Your token never leaves your machine** except in requests to your own Canvas
  instance. This project has no server, no telemetry, and no analytics.
