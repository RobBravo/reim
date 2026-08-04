# Security Policy

## Supported versions

REIM is pre-1.0. Security fixes are applied to the latest release on `main`.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ |
| < 0.1   | ❌ |

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
on this repository (Security → Report a vulnerability).

Please include:

- What the issue is and why it matters.
- Steps to reproduce, or a proof of concept.
- Affected version or commit.
- Any suggested fix.

**What to expect**

| Stage | Target |
|-------|--------|
| Acknowledgement | within 5 business days |
| Initial assessment | within 10 business days |
| Fix or mitigation plan | communicated once assessed |

We will keep you updated, credit you in the advisory unless you prefer
otherwise, and coordinate disclosure timing with you.

Please give us reasonable time to release a fix before disclosing publicly, and
do not access or modify data that is not yours while investigating.

## Scope

**In scope:** the REIM codebase — API, CLI, ingestion, database layer, container
images and CI configuration. Examples of what we want to hear about: SQL
injection, authentication or authorization flaws in anything we add later,
secret leakage, SSRF through connector configuration, denial of service via
unbounded queries or exports, dependency vulnerabilities we ship, and container
misconfiguration.

**Out of scope:** vulnerabilities in the official source websites and APIs REIM
reads (report those to the publisher), issues in a deployment's own
infrastructure, and findings that require an already-compromised host.

Note that REIM v0.1.0 has **no authentication layer** — the API is read-only and
intended to sit behind a gateway. "The API is unauthenticated" is a documented
design decision, not a vulnerability. See the Roadmap for API keys.

## Handling secrets

REIM is built so that **no secret ever lives in the repository**.

- All configuration comes from environment variables prefixed `REIM_`.
- `.env` is git-ignored; only `.env.example` is committed, and it contains
  placeholder development credentials only.
- The database URL is never written into `alembic.ini` — `alembic/env.py` reads
  it from settings at runtime.
- `reim db check` and the CLI redact passwords when printing a connection string.
- CI runs `gitleaks` on every push and pull request.
- Credentials in `docker-compose.yml` (`reim`/`reim`) are local development
  defaults. **Never reuse them anywhere reachable from a network you do not
  control.**

If you find a committed secret, report it privately as above. If you commit one
by accident, rotate it immediately — rewriting history is not sufficient, since
the value must be assumed compromised.

## Deployment hardening

REIM's defaults favour local development. Before exposing an instance:

- Set `REIM_ENVIRONMENT=production`.
- **Narrow `REIM_CORS_ALLOW_ORIGINS`** — the default `*` is for local use.
- Put a reverse proxy or API gateway in front, with TLS and rate limiting.
- Use a dedicated PostgreSQL role with only the privileges it needs; the API
  itself performs no writes, so it can run with a read-only role while the CLI
  uses a writing role.
- Do not expose the PostgreSQL port publicly.
- Restrict `/metrics` to your monitoring network, or set
  `REIM_METRICS_ENABLED=false`.
- Lower `REIM_MAX_PAGE_SIZE` and `REIM_MAX_EXPORT_ROWS` to values matching your
  capacity.
- Run the published container as-is: it already runs as a non-root user
  (uid 10001) and carries no build toolchain.
- Keep dependencies patched; rebuild the image regularly for base-image fixes.

## Responsible use of official sources

Not a vulnerability class, but a security-adjacent obligation REIM takes
seriously. Connectors must respect the institutions they read from: bounded
retries with exponential backoff, realistic timeouts, no parallel hammering, and
an identifying `REIM_HTTP_USER_AGENT` on every request so operators can contact
us. If you find a connector behaving abusively toward a public institution,
report it as a bug — we will treat it with the same urgency as a security issue.
