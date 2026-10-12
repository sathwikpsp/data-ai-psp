# Security boundaries

This reference platform handles usage metadata, not prompts or completions. Unknown fields are rejected and rejected raw records are not persisted. Request/team identifiers can still contain sensitive business information: choose pseudonymous identifiers and apply storage access controls.

Production mode requires a bearer token of at least 32 characters. Generate a random token; length validation does not measure entropy. The token grants full access to this one workspace. There is no multi-tenant isolation, SSO, per-user role system, or encrypted-at-rest storage implemented in the application. Use platform encryption and a TLS reverse proxy before accepting real usage.

The API accepts at most 2 MB per mutation request and 5,000 events per batch. Its SQL queries use parameterized values. No user-supplied SQL, file paths, model downloads, remote URLs, or shell commands are executed. The evidence assistant is a deterministic router with no external tools. Browser rendering uses text nodes for data; it does not render arbitrary model HTML.

Rate limiting, request/connection timeouts, authorization beyond one workspace token, retention/deletion policies, and backup encryption must be implemented at the deployment boundary. The in-process lock and bounded request size are not a denial-of-service defense for an untrusted public internet deployment. Keep the demo read-only and synthetic.

Never commit `.env`, warehouse files, live exports, tokens, or real event feeds. Use a private external data directory for operational runs. This repository's `reports/` contains only synthetic examples. When sharing a vulnerability report, provide a minimal redacted reproduction through a private maintainer channel; do not put credentials or customer data in a public issue.
