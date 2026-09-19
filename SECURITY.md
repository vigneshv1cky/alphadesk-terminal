# Security policy

AlphaDesk holds people's market-data credentials, so security reports are
welcome and taken seriously.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting — the
**Report a vulnerability** button under this repository's **Security** tab —
or email **muruganvignesh0810@gmail.com** with "AlphaDesk security" in the
subject.

Please include what an attacker can do, the steps to reproduce it, and the
version or commit you tested. A proof of concept helps; a patch is welcome
but not required.

This is a one-maintainer project, not a company with a rota. Expect a first
reply within about a week. There is no bounty programme.

## What to test against

Test your **own instance**, self-hosted from this repository. Do not test
against the hosted service, other people's accounts, or the data vendors'
APIs. Denial-of-service testing is out of scope everywhere.

## What is in scope

Anything that would let someone reach another reader's data or credentials,
or act as them:

- reading, exporting or decrypting another reader's vendor keys, which are
  sealed with AES-256-GCM (a report that the sealing itself is broken or
  misused is very much in scope);
- crossing the per-reader boundary: any cache, query or agent tool that
  serves one reader's vendor data to another;
- session handling, single sign-on, the agent access tokens and the OAuth
  flow for connector apps, including consent and token handling;
- the agent tools gaining any write surface, or running as anyone other than
  the reader whose credential they carry;
- server-side request forgery, injection, or remote code execution;
- filing, transcript or headline text reaching something that acts on it —
  that text is attacker-reachable in principle and must stay inert data.

## What is not a vulnerability

- Missing rate limits on an endpoint that only fetches with your own key.
- A vendor's data being wrong, delayed or refused by your plan.
- A self-hosted instance run without sign-in (`ALPHADESK_AUTH=off`), which is
  a documented single-account mode for local use.
- Anything requiring an already-compromised machine or an already-stolen
  credential.
- Reports produced by a scanner with no demonstrated impact.

## If you run your own instance

- **`ALPHADESK_VAULT_KEY` seals every stored vendor key.** Keep it out of the
  repository and back it up; losing it makes stored keys unreadable, and
  leaking it exposes them all.
- **Set `ALPHADESK_COOKIE_SECURE=1` behind HTTPS**, and set
  `ALPHADESK_BASE_URL` so sign-in redirects and the agent host allowlist are
  correct.
- **Do not expose the standalone agent server** (`python -m alphadesk.main
  mcp`): it has no reader identity and no gate.
- **Vendor keys are per reader.** If you open your instance to other people,
  each of them connects their own.
