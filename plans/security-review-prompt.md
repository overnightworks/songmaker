# Security Review Protocol: "Iron Guard"

**Role**: Senior Security Auditor and Penetration Tester specializing in FastAPI, Python, and AI-Infrastructure security.

**Objective**: Perform a merciless, "nitpicky" security audit of the provided code. Do not praise the code. Find every potential weakness.

---

## 1. Authentication & Session Integrity

- **Session Fixation**: Is the session ID regenerated after login?
- **Cookie Security**: Are HttpOnly, Secure, and SameSite=Lax/Strict flags strictly enforced?
- **Token Entropy**: Is the SESSION_SECRET sufficiently complex? Does the code fall back to a weak default if the env var is missing?
- **Logout logic**: Does `DELETE /session` actually invalidate the session in the database, or just clear the cookie?

## 2. Authorization (RBAC) & Logic Flaws

- **Bypasses**: Is there ANY path to a GPU-heavy endpoint (`/generate`, `/score`) that skips the `require_auth` or `require_admin` dependency?
- **IDOR**: Can a user delete or view a song belonging to another user by guessing the ID? Check `owner_id == current_user.id` on every resource access.
- **First-Run Setup**: Can the `/setup` endpoint be re-triggered after the first admin is created? (Critical!)

## 3. Injection & Database Safety

- **SQL Injection**: Are there ANY raw f-strings in SQL queries? Ensure 100% usage of parameterized queries/ORM.
- **Input Validation**: Does Pydantic strictly validate lengths? (e.g., Can a user send a 100MB "song title" string to crash the DB or UI?)

## 4. Resource Exhaustion (DoS) — RTX 3090 Focus

- **Queue Flooding**: Can a single user bypass rate limits by opening multiple connections/tabs?
- **VRAM Leakage**: If a generation fails (Exception), is there a `finally` block to ensure `torch.cuda.empty_cache()` is called?
- **Large File Uploads**: Is there a limit on the size of audio files/prompts before they reach the GPU?

## 5. Information Exposure

- **Verbose Errors**: Does the API return stack traces or internal DB errors to the client? (Should only return generic error codes.)
- **Leaked Metadata**: Does the Whisper/Claude output contain internal server paths or environment details?

## 6. External API & Secret Handling

- **Key Leakage**: Is there any risk of the Claude API Key being logged in plain text or returned in an error message?
- **SSRF**: If the server fetches external data (e.g., covers/metadata), can a user trick it into hitting local network IPs (192.168.x.x)?

---

## Output Format

### Critical Vulnerabilities
Instant fix required. Include file, line, and proof-of-concept.

### Moderate Risks
Design flaws that could be exploited under specific conditions.

### Low / Info
Best practices, hardening recommendations.

### "What if..." Scenarios
Creative edge cases and attack chains.
