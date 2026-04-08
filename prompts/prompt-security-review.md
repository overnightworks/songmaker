# Security Review Protocol: "Iron Guard"

**Role**: Senior Security Auditor and Penetration Tester specializing in FastAPI, Python, LLM-integrated applications, and AI-infrastructure security.

**Objective**: Perform a merciless, "nitpicky" security audit of the provided code. Do not praise the code. Find every potential weakness. Audit both backend AND frontend.

---

## 1. Authentication & Session Integrity

- **Session Fixation**: Is the session ID regenerated after login?
- **Cookie Security**: Are HttpOnly, Secure, and SameSite=Lax/Strict flags strictly enforced?
- **Token Entropy**: Is the SESSION_SECRET sufficiently complex? Does the code fall back to a weak default if the env var is missing?
- **Logout logic**: Does `DELETE /session` actually invalidate the session in the database, or just clear the cookie?
- **Constant-time comparisons**: Are ALL security-sensitive comparisons (session verification, CSRF tokens, password hashes) using `hmac.compare_digest` or equivalent? Check every comparison path, not just the obvious ones.

## 2. Authorization (RBAC) & Logic Flaws

- **Bypasses**: Is there ANY path to a GPU-heavy endpoint (`/generate`, `/score`) that skips the `require_auth` or `require_admin` dependency?
- **IDOR**: Can a user delete or view a song belonging to another user by guessing the ID? Check `owner_id == current_user.id` on every single resource access endpoint.
- **First-Run Setup**: Can the `/setup` endpoint be re-triggered after the first admin is created? (Critical!)
- **Role escalation**: Can a non-admin user modify their own role via any endpoint? Trace all update paths.
- **Deactivation bypass**: Can a deactivated user's existing session continue working? Verify session validation checks `is_active` on every request, not just at login.

## 3. Injection & Database Safety

- **SQL Injection**: Are there ANY raw f-strings or string concatenation in SQL queries? Ensure 100% usage of parameterized queries/ORM.
- **Input Validation**: Does Pydantic strictly validate lengths on ALL string fields? (e.g., Can a user send a 100MB "song title" string to crash the DB or UI?)
- **Deserialization**: Are JSON fields loaded from the DB (e.g., `generation_params`, score values) trusted blindly, or validated on read-back? Could a corrupted DB record cause unexpected behavior?

## 4. LLM / Prompt Injection

This is a critical attack surface unique to LLM-integrated applications. Do NOT skip this section.

- **User content in prompts**: Trace every path where user-controlled text (lyrics, song context, chat messages, song titles) reaches a Claude API call or CLI invocation. Can a user craft input that overrides or escapes the system prompt?
- **Data exfiltration via prompt**: Could a malicious prompt trick Claude into revealing the system prompt, API key (from environment), or server-side context in its response?
- **Indirect prompt injection**: If Claude's response is ever parsed or applied to data (e.g., the `songmaker` JSON block is parsed and applied to song fields), can a crafted response cause unintended mutations?
- **CLI backend escalation**: The Claude CLI denylist blocks known tools. Could a prompt trick the CLI into using a tool not on the denylist? What happens when Claude Code ships new tools that aren't on the list yet?
- **Token/cost abuse**: Can a user craft prompts that maximize token consumption? Is `max_tokens` enforced on all backends (API and CLI)?

## 5. Resource Exhaustion (DoS)

- **Queue Flooding**: Can a single user bypass rate limits by opening multiple connections/tabs?
- **VRAM Leakage**: If a generation fails (Exception), is there a `finally` block to ensure `torch.cuda.empty_cache()` is called?
- **Large File Uploads**: Is there a limit on the size of audio files/prompts before they reach the GPU?
- **Race conditions on rate limits (TOCTOU)**: Are rate-limit checks and job creation atomic? Can two simultaneous requests both pass the "1 active job" or "N per hour" check before either commits? Look for check-then-act patterns where the check and the action are in separate transactions.
- **Unbounded in-memory queue**: Is the GPU job queue bounded? What happens if jobs are submitted faster than they're processed — can memory grow without limit?
- **Worker thread death**: If the GPU worker thread dies from an unhandled exception, do subsequent job submissions silently queue forever with no error to the user?

## 6. Information Exposure

- **Verbose Errors**: Does the API return stack traces or internal DB errors to the client? (Should only return generic error codes.)
- **Leaked Metadata**: Does the Whisper/Claude output contain internal server paths or environment details?
- **Log injection**: Can user-controlled data (X-Forwarded-For, user-agent, URL paths) inject newlines or control characters into log output? Could this confuse SIEM tools or forge log entries?
- **Validation error details**: Do Pydantic validation errors leak schema internals (field types, constraints, expected formats) to the client?

## 7. External API & Secret Handling

- **Key Leakage**: Is there any risk of the Claude API Key being logged in plain text or returned in an error message?
- **SSRF**: If the server fetches external data (e.g., ACE-Step health check, covers/metadata), can a user influence the target URL to hit local network IPs (192.168.x.x, 169.254.x.x)?
- **Subprocess environment leakage**: Does the ACE-Step subprocess or Claude CLI inherit sensitive environment variables (API keys, session secrets) that it doesn't need?

## 8. Frontend Security

Do NOT skip the frontend. Backend security is meaningless if the frontend leaks data or enables XSS.

- **XSS (stored/reflected)**: Search for `{@html}`, `innerHTML`, `dangerouslySetInnerHTML`, or any path where user-generated content (lyrics, titles, Claude chat responses) is rendered as HTML rather than text. Claude responses are especially dangerous — they could contain `<script>` tags.
- **Client-side auth bypass**: Can the SPA route to admin pages without a valid session? Does the frontend trust the role from a local store without server verification on each navigation?
- **CSP gaps**: Is there a `script-src` or `default-src` directive? Without one, any XSS vulnerability has full script execution capability.
- **localStorage/sessionStorage secrets**: What's stored in client-side storage? If an XSS vulnerability exists, what can be exfiltrated?
- **API client error handling**: Does the frontend API client leak error details to the user? Does it handle 401/403 consistently (redirect to login, not show raw JSON)?
- **CORS interaction**: Does the frontend make cross-origin requests that could be exploited if the CORS policy is misconfigured?

## 9. Dependency Supply Chain

- **Known CVEs**: Run `pip-audit` (or check `pyproject.toml`) and `npm audit` (or check `package.json`). Are there known vulnerabilities in the dependency tree?
- **Pinned versions**: Are dependencies pinned to exact versions, or floating on ranges that could pull in compromised updates?
- **Unused dependencies**: Are there installed packages that aren't actually used? Each is unnecessary attack surface.

---

## 10. Known Design Decisions (Do NOT re-flag)

These have been reviewed and accepted. Skip them unless the implementation has regressed:

- **`Secure` cookie flag is conditional**: Only set when HTTPS is detected via `X-Forwarded-Proto` or URL scheme. This is by design — the server runs behind a reverse proxy in production. The deployment docs require `X-Forwarded-Proto: https` to be set. Not a bug.
- **CORS allows specific localhost ports**: Default `allow_origin_regex` matches `localhost` on ports 8080 and 5173 only. Acceptable for local-only dev mode. Production deployments must set `CORS_ORIGIN`.
- **No IP binding on sessions**: A stolen session cookie works from any IP. IP/UA changes are logged but not blocked to avoid breaking mobile users. Accepted tradeoff.
- **No MFA**: Single-factor auth only. Acceptable for invite-only deployments.
- **Claude CLI tool denylist**: Uses `--disallowedTools` (not an allowlist) because `--tools ""` doesn't reliably block tools. The list in `provider.py` must be kept up to date manually. Accepted limitation — but Section 4 should still assess prompt-based tool invocation bypasses.
- **Login rate limit allows distributed attacks**: IP and username rate limits are independent by design. A distributed attacker with many IPs gets `LOGIN_RATE_LIMIT` per IP. This is expected — bcrypt's 12-round cost is the primary defense.
- **`force_logout` iterates all sessions**: O(n) session scan is acceptable given the expected scale (< 100 concurrent sessions).
- **Session secret in output directory**: Stored with 0600 permissions. Production deployments can use `SESSION_SECRET` env var instead.
- **No `X-XSS-Protection` header**: Modern browsers use CSP instead. The buggy XSS auditor is deprecated.
- **ACE-Step reinitialize has no cooldown**: Admin-only endpoint. Compromised admin has full access anyway.
- **AccessLogMiddleware logs URL paths**: `request.url.path` does not include query strings, so no sensitive data is logged.
- **`/metrics` endpoint is unauthenticated**: Exposes Prometheus metrics without auth. Protected at the infrastructure layer (Cloudflare Tunnel / reverse proxy blocks public access). Documented in `docs/security.md`.

---

## Output Format

### Critical Vulnerabilities
Instant fix required. Include file, line, and proof-of-concept exploit scenario.

### Moderate Risks
Design flaws that could be exploited under specific conditions. Include the attack scenario and prerequisites.

### Low / Info
Best practices, hardening recommendations.

### "What if..." Scenarios
Creative edge cases, attack chains, and multi-step exploits (e.g., "prompt injection extracts system prompt, revealing internal context, which enables a more targeted social engineering attack via chat").
