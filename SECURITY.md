# Security Policy

## Supported versions

Carivyo is currently a local single-user MVP. Security fixes target the latest
revision on the default branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose local resume
artifacts, permit shell execution, bypass URL controls, or corrupt provenance.
Use GitHub's private vulnerability reporting feature when enabled for the
repository. If it is unavailable, contact the repository owner privately.

Include affected versions, reproduction steps, expected impact, and any
suggested mitigation. Do not include real resumes, provider credentials, or
other personal information in a report.

## Security boundary

Carivyo binds to loopback, uses a random local session token, validates browser
origins, restricts artifact permissions, rate-limits API requests, invokes
controlled AI runtimes with argument arrays, and allowlists official
application routes.

This MVP does not implement application-managed field encryption, encrypted
backup archives, or a hosted multi-user authorization model. Use it on a
device protected by operating-system account security and full-disk
encryption. See `docs/readiness.md` for the complete boundary.
