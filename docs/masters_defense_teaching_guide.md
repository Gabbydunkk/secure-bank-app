# Secure Banking System Teaching and Defense Guide

## 1. What This System Is

This project is a secure banking application built as a full-stack system:

- The backend is a FastAPI application that handles authentication, MFA, fraud scoring, transaction processing, audit logging, role-based access control, and admin operations.
- The frontend is a React + TypeScript application that gives different user experiences to customers, fraud analysts, and administrators.
- The database layer stores users, sessions, MFA secrets, transactions, fraud alerts, audit logs, known devices, and behavior baselines.

The most important story to tell is this:

> We did not build "just a banking app UI." We built a security-first transaction platform where every important action passes through layered controls: validation, authentication, authorization, fraud analysis, state transitions, and audit logging.

That single sentence is the backbone of your defense.

---

## 2. How To Teach This To A Beginner

When teaching someone with minimal coding background, never start with code syntax. Start with the business problem.

Use this sequence:

1. Explain the real-world problem.
2. Explain the system as a set of cooperating departments.
3. Explain the request journey from browser to database and back.
4. Only then go file by file.
5. For each file, explain:
   - What problem this file solves
   - Why this file exists separately
   - What inputs it receives
   - What outputs it produces
   - What security or reliability rule it enforces
   - What would break if it did not exist

When defending, use this six-part pattern for every file:

1. `Purpose`: what this file is responsible for
2. `Why separate`: why we did not mix it into another file
3. `Key logic`: the main code path inside it
4. `Security value`: what risk it reduces
5. `Design value`: what software engineering principle it demonstrates
6. `Likely questions`: what a panel or interviewer may ask next

---

## 3. The Big Architectural Story

Before going file by file, explain the system in layers.

### Frontend layer

This is the user-facing part. It renders pages, stores session state in memory/browser storage, calls the backend API, protects routes, and presents different interfaces for normal users, analysts, and admins.

### API layer

This is the HTTP boundary. It receives requests, validates input, enforces authentication and authorization, and translates business errors into HTTP responses.

### Service layer

This is where business rules live. For example:

- How login works
- How MFA is verified
- How fraud is scored
- How transactions change state
- How admin actions are audited

### Data layer

This is the persistent state of the system. It models users, sessions, devices, transactions, alerts, and logs.

### Security layer

This cuts across everything:

- Password hashing
- JWT creation and verification
- MFA secrets encryption
- token hashing
- session revocation
- role-based access control
- rate limiting
- fraud scoring
- audit logs

### Why this architecture is strong

Because each layer has a clear job:

- Routers do HTTP work
- Services do business logic
- Models define stored data
- Schemas define allowed shapes
- Core utilities handle security primitives
- Frontend pages focus on user interaction

This separation is one of the strongest things to defend in a master's project.

---

## 4. End-to-End Story You Should Present First

Use this as your main verbal walkthrough.

### Story A: User login

1. The frontend login page collects credentials.
2. The frontend auth context sends them to `/auth/login`.
3. The backend router accepts the HTTP request.
4. The auth service verifies the password hash.
5. The service checks account status and lock state.
6. The fraud engine evaluates login context like IP, location, and device fingerprint.
7. If MFA is enabled, a temporary `mfa_pending` token is issued instead of full access.
8. If login succeeds, a session is created in the database.
9. JWT access and refresh tokens are returned.
10. The frontend stores tokens and fetches `/auth/me`.
11. Route guards unlock the correct UI based on the user's role.

### Story B: Transaction creation

1. The frontend transaction page collects amount, recipient, and description.
2. The frontend sends a request to `/transactions/`.
3. The router enforces authentication and the `transfer_authorized` scope.
4. The transaction service runs fraud checks before committing anything important.
5. The transaction is classified as pending, flagged, or blocked.
6. A fraud alert may be created.
7. An audit log is written.
8. The frontend shows success, flagged review, or blocked status.

### Story C: Analyst review

1. Analysts open the fraud workspace.
2. The frontend fetches fraud alerts and reviewable transactions.
3. The backend only allows analyst/admin roles through dependency checks.
4. Analysts can mark alerts as investigating, resolve them, or block transactions.
5. These actions are recorded for accountability.

### Story D: Admin control

1. Admins access a stricter route guarded both on frontend and backend.
2. They can list users, change roles, change account status, or revoke sessions.
3. Every change is logged in the audit trail.
4. Dangerous actions like suspension also invalidate active sessions.

---

## 5. File-by-File Teaching Order

Do not teach files in alphabetical order. Teach them in execution order.

### Phase 1: Backend entry and system setup

#### `app/main.py`

Purpose:
This is the backend entry point. It creates the FastAPI app, configures middleware, and mounts all routers.

Why it matters:
This file is the composition root of the backend. It is where all major modules are assembled into one running application.

Key points to explain:

- CORS middleware controls which frontend origins may call the API.
- Trusted host middleware helps reduce host-header attacks.
- Routers are mounted under the API prefix from config.
- Health endpoints exist for liveness and monitoring.

Defense angle:
You should say this file is intentionally thin. A strong design keeps the entry point focused on composition, not business logic.

Likely panel questions:

- Why not put logic directly in `main.py`?
- Why use middleware here instead of in every route?
- Why are docs potentially disabled in production?

#### `app/core/config.py`

Purpose:
Loads environment-driven configuration using settings.

Why it matters:
Security-sensitive values like database URL and secret key are not hardcoded.

Key points:

- Environment variables allow safer deployment across dev, test, and production.
- Fraud thresholds are configurable without code changes.
- CORS origins are parsed from configuration.

Strong defense statement:

> We treated configuration as externalized policy, not embedded code.

Likely questions:

- Why is `SECRET_KEY` required with no default?
- Why keep fraud thresholds configurable?

#### `app/models/database.py`

Purpose:
Creates the SQLAlchemy engine, session factory, and base class.

Why it matters:
Every database operation flows through this file.

Key points:

- Connection pooling improves performance and resilience.
- SSL mode is configurable, with production defaulting to secure behavior.
- `get_db()` is used by dependency injection so sessions are opened and closed correctly.

Likely questions:

- Why use dependency injection for DB sessions?
- Why configure pool size explicitly?

### Phase 2: Data modeling

#### `app/models/user.py`

Purpose:
Defines the ORM models for the whole system.

What to say:
This file models the business world of the application:

- `User`
- `MFASecret`
- `Session`
- `LoginAttempt`
- `Transaction`
- `FraudAlert`
- `UserBehaviorPattern`
- `AuditLog`
- `OAuthProvider`
- `KnownDevice`

Crucial defense points:

- The database itself enforces valid values through check constraints.
- Security is not left to frontend trust alone.
- Relationships make it possible to trace a user through sessions, transactions, alerts, and logs.

Very important line to say:

> The data model reflects both business functionality and security accountability.

Likely questions:

- Why store session records in the database if JWTs are stateless?
Answer: to support revocation, logout, and session liveness checks.
- Why model `KnownDevice` separately?
Answer: to support device anomaly scoring.
- Why store `AuditLog` as a first-class table?
Answer: because in critical systems, explainability and forensics are requirements, not extras.

### Phase 3: Security primitives

#### `app/core/security.py`

Purpose:
Handles password hashing, JWT creation, refresh token generation, hashing, and verification.

Key teaching points:

- Passwords are never stored as plain text.
- Access tokens are short-lived JWTs.
- Refresh tokens are random opaque strings, not JWTs.
- Refresh tokens are hashed before storage.
- MFA pending tokens are separate from access tokens and have a different type.

Critical defense point:

> We deliberately separated token types so an MFA token can never behave like a normal access token.

Likely questions:

- Why hash tokens in the database?
- Why use access plus refresh instead of one long token?
- Why distinguish `type=access` and `type=mfa_pending`?

#### `app/core/totp.py`

Purpose:
Implements TOTP MFA and encrypts MFA secrets and backup codes.

Key teaching points:

- MFA secrets are sensitive because whoever owns them can generate future codes.
- Secrets are encrypted at rest.
- Backup codes are single-use and stored hashed or encrypted safely.
- TOTP follows the standard rolling-code idea used by authenticator apps.

Best non-technical explanation:

> Password proves what you know. MFA proves what you have. This file implements the second proof.

Likely questions:

- Why encrypt MFA secrets instead of hashing them?
Answer: because the server must recover them to verify codes.
- Why support backup codes?
Answer: recovery without disabling security entirely.

#### `app/core/rate_limiter.py`

Purpose:
Applies in-memory rate limiting to sensitive endpoints.

Key teaching points:

- Login, MFA verification, and registration are brute-force targets.
- Sliding-window logic is fairer and more secure than a naive fixed window.
- Current implementation is good for a single-process deployment and can later be replaced with Redis.

Likely questions:

- Why not Redis now?
- What changes in production with multiple app instances?

### Phase 4: API dependency and authorization layer

#### `app/api/deps.py`

Purpose:
Defines reusable dependencies for auth, session validation, scope checks, IP extraction, and role gates.

Why it matters:
This is a major security boundary.

Key points:

- `get_current_user` validates JWT and loads the user.
- `get_current_session` also checks that the session is still active in the database.
- `require_scope`, `require_analyst`, and `require_admin` enforce least privilege.

Strong defense line:

> Authentication answers "who are you?" Authorization answers "what are you allowed to do?" This file keeps those separate.

Likely questions:

- Why check the session table if JWT is already valid?
- Why create named dependencies like `require_analyst`?
- Why is role rank useful?

### Phase 5: Backend HTTP routers

#### `app/api/auth_router.py`

Purpose:
Defines the public and authenticated auth endpoints.

Important endpoints:

- register
- login
- refresh
- logout
- change-password
- me
- mfa setup, confirm, verify, disable

How to explain it:
The router is the HTTP translator. It does not own the deep business rules. It receives validated input, calls services, and maps service outcomes to HTTP status codes.

Likely questions:

- Why return `202 Accepted` for MFA-required login?
- Why is `/auth/mfa/verify` public?
Answer: because the `mfa_token` itself is the credential for that step.

#### `app/api/transaction_router.py`

Purpose:
Handles transaction creation, listing, fetching, review, clearing, blocking, and processing.

Crucial story:
This file shows layered control:

- auth dependency
- transfer scope check
- analyst-only review operations
- service layer for state transitions

Likely questions:

- Why can analysts block transactions they do not own?
- Why return `404` instead of `403` for another user's transaction?
Answer: to prevent enumeration attacks.

#### `app/api/fraud_router.py`

Purpose:
Lists fraud alerts and lets analysts update their status.

Key points:

- Regular users see only their own alerts.
- Analysts and admins get global review visibility.
- Resolution notes are required when closing a case.

Likely questions:

- Why allow analysts to change alerts across users?
- Why track status values like open, investigating, resolved, false positive?

#### `app/api/audit_router.py`

Purpose:
Exposes the user's audit trail as read-only data.

Critical defense point:

> Audit logs are append-only evidence, not normal editable records.

Likely questions:

- Why no create/update/delete endpoints?
- Why restrict users to their own logs?

#### `app/api/admin_router.py`

Purpose:
Provides high-privilege system administration endpoints.

Key points:

- Entire router is guarded by `require_admin`.
- Admins can manage users, sessions, roles, statuses, and system policy settings.
- Admin actions are auditable.

Likely questions:

- Why prevent admins from changing their own role or status?
- Why do role changes take effect on next refresh instead of instantly?

#### `app/api/user_router.py`

Purpose:
Supports self-service profile and device operations.

Key points:

- Users can update profile data.
- Users can inspect known devices.
- Users can remove their own devices.

Likely questions:

- Why is removing a device useful?
Answer: because future login from that device becomes suspicious again.

### Phase 6: Backend service layer

#### `app/services/auth_service.py`

Purpose:
Owns login, registration, token refresh, logout, password change, profile updates, and MFA-completed login.

This is one of the most important files in the entire project.

How to explain it:

- It resolves users from login data.
- It validates credentials against password hashes.
- It enforces lockout rules.
- It triggers MFA when required.
- It runs fraud checks before token issuance.
- It creates sessions and tokens atomically.
- It logs attempts for auditability.

Best defense statement:

> Authentication here is not a single yes/no check. It is a pipeline: identity proof, account state validation, fraud evaluation, session creation, and token issuance.

Likely questions:

- Why run fraud checks before session creation?
- Why create a session row if JWT is stateless?
- Why is device registration done after successful login?

#### `app/services/mfa_service.py`

Purpose:
Owns MFA enrollment, confirmation, verification, and disable flow.

Key points:

- Setup does not automatically enable MFA.
- Confirmation proves the user really enrolled the authenticator.
- Disable requires a valid MFA code, not just a session.

Strong defense line:

> We designed MFA enrollment as a two-step commitment process to avoid user lockout and reduce misuse.

Likely questions:

- Why not enable MFA immediately at setup?
- Why require a code to disable MFA?

#### `app/services/fraud_service.py`

Purpose:
Implements the explainable fraud rule engine.

This is another major defense file.

Rules currently include:

- restricted location
- login velocity
- large amount
- device anomaly
- behavior pattern anomaly

Key design strengths:

- Rule interface supports extensibility
- Engine aggregates rule outputs
- Score is mapped to action: allow, flag, challenge, block
- Alert creation is separated from scoring

Excellent defense line:

> Our fraud engine is intentionally explainable. Instead of a black-box score, we can say which rule fired, why it fired, and how much it contributed.

Likely questions:

- Why use rules instead of machine learning?
- How would you scale this toward ML later?
- Why is explainability important in financial systems?

#### `app/services/transaction_service.py`

Purpose:
Implements transaction creation, listing, fetching, processing, blocking, and clearing.

Key concepts to emphasize:

- Fraud is checked before final commit.
- Processing follows a state machine.
- Invalid transitions are rejected.
- Audit logs capture state changes.
- Behavior patterns are updated only after successful completion.

Strong defense line:

> We treated transaction processing as a controlled state machine, not a loose series of updates.

Likely questions:

- Why a state machine?
- Why is a flagged transaction not auto-processed?
- Why update behavior only after completion?

#### `app/services/admin_service.py`

Purpose:
Owns privileged user-management logic and system policy settings.

Key points:

- Admin actions are audited
- disabling an account revokes sessions
- self-modification is restricted
- some settings are process-local demo policy and should move to DB in production

Likely questions:

- What would you change before production?
- Why is policy store in-memory today?

#### `app/services/device_service.py`

Purpose:
Tracks known devices for users.

Key point:
Without this file, device anomaly detection would be noisy and meaningless because every device would look permanently new.

#### `app/services/behavior_service.py`

Purpose:
Builds a user behavior baseline from completed transactions.

Key ideas:

- exponential moving average adapts over time
- stale max resets prevent historical outliers from weakening rules forever
- only trusted completed transactions train the profile

Likely questions:

- Why EMA instead of simple average?
- Why never learn from flagged or blocked transactions?

### Phase 7: Frontend application shell

#### `secure-bank-frontend/src/main.tsx`

Purpose:
Frontend bootstrapping. Renders the React app.

Explain it simply:
This is where the browser loads the application.

#### `secure-bank-frontend/src/App.tsx`

Purpose:
Defines the route tree and wraps the app with auth context.

Key points:

- public routes vs protected routes
- role-based route guards
- separate analyst and admin sections

Likely questions:

- Why also enforce roles in frontend if backend already does?
Answer: frontend improves UX, backend remains the real security boundary.

#### `secure-bank-frontend/src/contexts/AuthContext.tsx`

Purpose:
Global authentication state manager.

What to explain:

- hydrates session on startup
- handles login outcomes
- handles MFA pending flow
- exposes logout and role-checking logic
- listens for forced logout from HTTP layer

Critical defense point:

> We centralized auth state so every page uses one source of truth.

Likely questions:

- Why use context and reducer here?
- Why hydrate with `/auth/me` after storing tokens?

#### `secure-bank-frontend/src/lib/http.ts`

Purpose:
Central API client with interceptors.

Key points:

- attaches bearer token
- adds device fingerprint header
- refreshes tokens on 401
- retries queued requests after refresh
- clears session if refresh fails

Strong defense line:

> We kept session recovery logic in one place so token refresh does not become duplicated or inconsistent across pages.

Likely questions:

- What is the mutex doing?
- Why not refresh separately in every page?

#### `secure-bank-frontend/src/components/guards/RequireAuth.tsx`

Purpose:
Protects routes by auth and role.

Key points:

- handles loading state
- redirects unauthenticated users to login
- redirects unauthorized users to a 403-style page

### Phase 8: Frontend pages

#### `src/pages/auth/LoginPage.tsx`

Purpose:
Collects credentials and reacts to different login outcomes.

Key points:

- supports email or username
- handles blocked, locked, invalid, MFA-required, and success paths
- ties UI directly to security outcomes from the backend

Likely questions:

- Why distinguish all these login outcomes in the UI?

#### `src/pages/auth/MfaSetupPage.tsx` and `src/pages/auth/MfaVerifyPage.tsx`

Purpose:
Implement MFA enrollment and MFA login completion.

Key point:
These pages turn a security protocol into a usable workflow.

#### `src/pages/dashboard/DashboardPage.tsx`

Purpose:
Main customer landing page.

What to say:
It is not just visual. It pulls transactions and alerts, shows security posture, and changes available actions based on role and MFA status.

#### `src/pages/transactions/NewTransactionPage.tsx`

Purpose:
Creates transactions through the frontend.

Key points:

- local risk estimate gives user feedback
- actual backend risk still decides final result
- handles pending, flagged, blocked, and success states explicitly

Likely questions:

- Why compute a local risk estimate if the backend has the real fraud engine?
Answer: user feedback and transparency, not authority.

#### `src/pages/transactions/TransactionsPage.tsx` and `TransactionDetailPage.tsx`

Purpose:
Show ledger history and transaction details.

Defense angle:
These pages make system state observable and traceable to the user.

#### `src/pages/analyst/FraudWorkspacePage.tsx`

Purpose:
Dedicated fraud operations interface.

Why it is important:
This proves the system is not only user-facing; it supports operational investigation workflows.

Key points:

- alert queue
- case review
- action buttons
- transaction blocking and processing

Likely questions:

- Why a separate analyst interface?
- Why not let normal users resolve fraud flags themselves?

#### `src/pages/admin/AdminControlCenterPage.tsx`

Purpose:
Administrative operations console.

Key points:

- user search and filtering
- account status and role management
- force logout
- system policy edits
- audit stream

Likely questions:

- Why split admin and analyst roles?
- What operations are too sensitive for analysts?

### Phase 9: Tests

#### `tests/test_api.py`

Purpose:
Tests real router behavior using dependency overrides and mocks.

What to say:
This file proves our HTTP security boundaries and endpoint behavior.

#### `tests/test_mfa.py`

Purpose:
Tests MFA flows and token-type security guarantees.

Critical defense point:

> We did not just test happy paths. We tested security boundaries like wrong token types and public-vs-protected endpoint behavior.

#### `tests/test_fraud_scoring.py`

Purpose:
Verifies the fraud threshold mapping.

#### Other tests

- `test_rate_limiter.py`
- `test_roles.py`
- `test_admin.py`
- `test_device_service.py`
- `test_behavior_service.py`
- `test_transaction_state_machine.py`

Use these as proof that the project was engineered, not only coded.

### Phase 10: Database migrations

#### `alembic/env.py` and `alembic/versions/*`

Purpose:
Track schema changes over time safely.

Key point:

> In serious systems, schema evolution must be versioned and repeatable.

Likely questions:

- Why not rely on automatic table creation?
- Why use migrations in a master's project?

---

## 6. Crucial Software Engineering Principles To Defend

### Separation of concerns

The biggest architectural strength is that routers, services, models, schemas, and frontend state are separated cleanly.

### Defense in depth

The application does not rely on one control. It layers:

- input validation
- password hashing
- JWT verification
- session liveness checks
- role/scope checks
- MFA
- rate limiting
- fraud analysis
- audit logs

### Least privilege

Not every authenticated user can do everything.

- users can transact
- analysts can review and block
- admins can manage users and policy

### Explainability

Fraud decisions are rule-based and understandable.

### Auditability

Sensitive actions create evidence.

### State integrity

Transactions follow legal state transitions rather than ad hoc updates.

### Extensibility

Rules, policies, roles, and pages can grow without rewriting the whole system.

---

## 7. Questions A Master's Panel Is Likely To Ask

### Architecture

- Why did you choose FastAPI and React?
- Why a service layer instead of putting everything in routes?
- Why store sessions if JWT is stateless?

### Security

- Why use MFA pending tokens?
- How do you revoke a user's access immediately?
- How do you prevent brute force login attempts?
- What happens if a refresh token is stolen?
- Why are fraud checks done before token issuance or transaction completion?

### Fraud and risk

- Why use rule-based fraud scoring instead of machine learning?
- How would you reduce false positives?
- How are known devices and behavior baselines maintained?

### Data design

- Why store audit logs separately?
- Why use check constraints in the database?
- Why use migrations?

### Frontend design

- Why still protect routes on frontend if backend already enforces security?
- How does the frontend recover from expired tokens?
- How do role differences appear in the UI?

### Engineering maturity

- What would you change before production?
- What are current limitations?
- How would you scale rate limiting and policy settings?
- How would you improve observability and monitoring?

---

## 8. Strong Answers To Hard Questions

### "Why is JWT not enough by itself?"

JWT proves the token was issued by us and is unexpired. It does not by itself prove the session is still valid. By storing session rows and checking them for sensitive operations, we gain logout, revocation, and compromised-session containment.

### "Why not keep everything stateless?"

Because this is a critical financial system. Operational control matters more than architectural purity. Statelessness is convenient, but revocation and incident response are more important here.

### "Why do fraud checks happen before committing transactions?"

Because in a banking system, prevention is stronger than cleanup. Blocking risk before settlement is safer than reversing damage after the fact.

### "Why is explainability important?"

Because in financial systems, auditors, security teams, compliance officers, and customers may all need justification. A black-box answer is often not acceptable.

### "What are the current limitations?"

Be honest:

- rate limiting is in-memory, not distributed
- system policy settings are currently process-local
- some dashboard financial values are demo/static
- fraud scoring is rule-based, not adaptive ML
- transaction processing is synchronous placeholder logic rather than external rail integration

Honesty helps your defense. It shows maturity.

---

## 9. Best Way To Present This In A Defense

Use this presentation order:

1. Problem statement
2. System architecture diagram
3. Security-first design philosophy
4. End-to-end login flow
5. End-to-end transaction flow
6. Fraud analyst workflow
7. Admin governance workflow
8. Database model overview
9. Key files, one by one
10. Testing strategy
11. Limitations and future work

When you reach code, do not dump code on the panel. Use this pattern:

- show the file name
- explain its responsibility
- point to 2-3 important code decisions
- explain the security or engineering reason behind them

---

## 10. Fast File Narration Template

Use this exact script for each file:

> This file is `[file]`. Its job is `[purpose]`.  
> We kept it separate from `[other file]` because `[reason]`.  
> The most important logic here is `[main behavior]`.  
> From a security or reliability perspective, it protects us against `[risk]`.  
> From a software engineering perspective, it demonstrates `[principle]`.

Example:

> This file is `app/api/deps.py`. Its job is to centralize authentication and authorization dependencies. We kept it separate from the routers so every endpoint can reuse the same security rules consistently. The most important logic here is token validation, session liveness checks, and role/scope enforcement. From a security perspective, it protects us against unauthorized access and revoked-session misuse. From an engineering perspective, it demonstrates separation of concerns and reusable dependency injection.

---

## 11. What To Memorize Before You Defend

Memorize these 10 ideas exactly:

1. We designed the system in layers, not as one large code file.
2. Authentication and authorization are separate problems and are handled separately.
3. JWTs are combined with database-backed sessions to support revocation.
4. MFA uses a dedicated token type so token confusion is prevented.
5. Fraud checks happen before sensitive commits.
6. Transactions follow an explicit state machine.
7. Audit logs make critical actions traceable.
8. Role-based access control separates user, analyst, and admin responsibilities.
9. Known devices and behavior baselines reduce false positives and improve fraud context.
10. Tests cover both functionality and security boundaries.

---

## 12. Final Defense Positioning

If you need one closing statement for a panel, use this:

> This project demonstrates that secure software engineering is not just about adding encryption or login pages. It is about structuring the entire system so identity, authorization, fraud detection, transaction integrity, and accountability are built into every layer of the application.

---

## 13. Backend Code Defense Segments

This section is the backend-first, code-backed teaching sequence.

Use it exactly like this:

1. Start with one segment only.
2. Show the file.
3. Show the code block.
4. Explain the function/class line by line in simple language.
5. Then answer questions from that segment before moving on.

This is the safest way to defend the project without getting overwhelmed.

### Segment 1: Input Validation with Pydantic

Start here because this is the first place security begins.

File:
`app/schemas/user.py`

#### Code block: password complexity and age validation

```python
class UserCreate(UserBase):
    password: str = Field(..., min_length=12)
    role: UserRole = "user"

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def verify_age(cls, v: Optional[date]) -> Optional[date]:
        if v:
            today = date.today()
            age = today.year - v.year - (
                (today.month, today.day) < (v.month, v.day)
            )
            if age < 18:
                raise ValueError("Users must be at least 18 years old")
        return v
```

What this does:

- `Field(..., min_length=12)` enforces a minimum password length before business logic even runs.
- `@field_validator("password")` is a Pydantic validator that checks the password contents.
- The regex checks enforce uppercase, lowercase, number, and special character requirements.
- `@field_validator("date_of_birth")` ensures the user is at least 18 years old.

What to say in defense:

> We pushed validation as close as possible to the API boundary. That means weak or invalid data is rejected before it reaches business logic or the database.

Why this is good engineering:

- It reduces duplication because every route using this schema inherits the same rules.
- It improves security because malformed requests are stopped early.
- It improves maintainability because validation policy is centralized.

SOLID angle:

- `Single Responsibility Principle`: this schema is responsible for data shape and input validation, not database writes or token generation.

Likely questions:

- Why validate here and not only in the frontend?
Answer: frontend validation improves UX, but backend validation is the real trust boundary.
- Why use regex checks?
Answer: because password complexity is a policy rule and regex provides explicit enforceable criteria.

#### Code block: login identity validation

```python
class UserLogin(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    password: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def check_identifier_provided(self):
        if not self.email and not self.username:
            raise ValueError("Either email or username must be provided")
        return self
```

What this does:

- Allows login by email or username.
- Prevents empty identity requests from reaching the service layer.

What to say:

> This validator enforces the login contract. The user must provide at least one identity field, so the service layer never has to guess or handle undefined identity input.

---

### Segment 2: Password Hashing and Token Design

Files:

- `app/core/security.py`
- `app/schemas/auth.py`

#### Code block: password hashing

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
```

What this does:

- Uses bcrypt through Passlib.
- Hashes passwords before storing them.
- Verifies future logins by comparing the submitted password to the stored hash.

What to say:

> We never store raw passwords. We store one-way bcrypt hashes, so even if the database is exposed, plain passwords are not recoverable from storage.

Likely questions:

- Why hash and not encrypt passwords?
Answer: passwords should be verified, not decrypted. Hashing is the correct one-way design.
- Why bcrypt?
Answer: it is designed for password storage and is intentionally slow enough to resist brute-force attacks better than fast hashes.

#### Code block: access token and MFA pending token

```python
def create_access_token(user_id: str | uuid.UUID, session_id: Optional[uuid.UUID] = None,
                        scopes: Optional[list[str]] = None) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": TokenType.ACCESS.value,
        "scopes": scopes if scopes is not None else [SCOPE_READ_ONLY],
    }
    if session_id is not None:
        payload["session_id"] = str(session_id)

    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire

def create_mfa_pending_token(user_id: str | uuid.UUID) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.MFA_PENDING_EXPIRE_MINUTES)

    payload = {
        "sub": str(user_id),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": TokenType.MFA_PENDING.value,
        "scopes": [],
    }

    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, expire
```

What this does:

- Creates a normal access token with scopes and optional session ID.
- Creates a different token for MFA completion.
- The MFA token carries no scopes and cannot authorize protected routes.

What to say:

> We intentionally separated token types. An access token authorizes API actions. An MFA pending token authorizes only the MFA completion step. That prevents token confusion attacks.

Critical interview question:

- Why not just use one token type for everything?
Answer: because mixing responsibilities increases security risk. Token purpose should be explicit and enforceable.

#### Code block: token-type enforcement

```python
def verify_mfa_pending_token(token: str) -> TokenPayload:
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    parsed = TokenPayload(**payload)

    if parsed.type != TokenType.MFA_PENDING:
        raise jwt.InvalidTokenError("Invalid token type: expected mfa_pending token")

    return parsed

def verify_access_token(token: str) -> TokenPayload:
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    parsed = TokenPayload(**payload)

    if parsed.type != TokenType.ACCESS:
        raise jwt.InvalidTokenError("Invalid token type: expected access token")

    return parsed
```

What to say:

> The system does not only decode tokens. It checks the declared token purpose. That means a token valid for one workflow cannot silently be reused in another.

SOLID angle:

- `Single Responsibility Principle`: this file handles security primitives only.
- `Open/Closed Principle`: token logic can be extended with new token types without rewriting unrelated business code.

---

### Segment 3: Authentication Service Flow

File:
`app/services/auth_service.py`

This is one of the strongest files to defend because it shows real business logic.

#### Code block: registration with hashed password

```python
def register_user(db: Session, data: UserCreate) -> User:
    if get_user_by_email(db, data.email):
        raise ValueError("Email already registered")
    if get_user_by_username(db, data.username):
        raise ValueError("Username already taken")

    user = User(
        email=data.email,
        username=data.username,
        password_hash=get_password_hash(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        phone_number=data.phone_number,
        date_of_birth=data.date_of_birth,
        account_status="active",
        role=getattr(data, "role", "user") or "user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
```

What to say:

> Registration is not just record creation. It first enforces uniqueness, then hashes the password, then stores a user in a least-privilege role by default.

Likely questions:

- Why not trust the database unique constraints alone?
Answer: we still want a clear application-level error path and friendly conflict handling.

#### Code block: failed login and lockout logic

```python
if not verify_password(login_data.password, user.password_hash):
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    failure_reason = "invalid_password"
    if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCK_MINUTES)
        failure_reason = "account_locked_due_to_failed_logins"
    _add_login_attempt(
        db, user_id=user.id, email=user.email, ip_address=ip_address,
        user_agent=user_agent, success=False, failure_reason=failure_reason,
    )
    db.commit()
    raise ValueError("Invalid email/username or password")
```

What this does:

- Verifies password against bcrypt hash.
- Tracks failed attempts.
- Locks the account temporarily after repeated failures.
- Writes an auditable login attempt record.

What to say:

> We do not simply reject a bad password. We record the attempt, increase the failure count, and eventually activate temporary lockout to slow brute-force attacks.

#### Code block: MFA diversion before token issuance

```python
if user.mfa_enabled:
    mfa_token, _ = create_mfa_pending_token(user.id)
    _add_login_attempt(
        db, user_id=user.id, email=user.email, ip_address=ip_address,
        user_agent=user_agent, success=False,
        failure_reason="mfa_verification_required",
        mfa_required=True,
        mfa_success=False,
    )
    db.commit()
    raise MFARequiredError(
        mfa_token=mfa_token, user_id=user.id, email=user.email
    )
```

What to say:

> Even after the password is correct, the system still withholds full access if MFA is enabled. Instead, it issues a limited-purpose MFA pending token and records that MFA is still incomplete.

#### Code block: fraud check before session creation

```python
fraud = fraud_service or FraudService()
fraud_input = FraudRuleInput(
    user_id=user.id,
    ip_address=ip_address,
    device_fingerprint=device_fingerprint,
    location_country=location_country,
    location_city=location_city,
)
fraud_result, _ = fraud.evaluate(
    db, fraud_input,
    create_alert_if_required=True,
    commit_alert=False,
)

if fraud_result.action == "block":
    ...
if fraud_result.action == "challenge":
    ...
```

What to say:

> Fraud is evaluated before we create a live session. That matters because once a session and tokens are issued, the attacker already has a foothold.

#### Code block: atomic session and token creation

```python
scopes = _scopes_for_user(user)
access_token, _ = create_access_token(
    user_id=user.id, session_id=None, scopes=scopes,
)
refresh_token = create_refresh_token()
refresh_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
session = SessionModel(
    user_id=user.id,
    access_token_hash=hash_token(access_token),
    refresh_token_hash=hash_token(refresh_token),
    device_fingerprint=device_fingerprint,
    ip_address=ip_address,
    user_agent=user_agent,
    location_country=location_country,
    location_city=location_city,
    is_active=True,
    expires_at=refresh_expires_at,
)
db.add(session)
db.flush()
```

What to say:

> We create a database-backed session record even though access uses JWT. That gives us revocation, logout, device context, and operational auditability.

SOLID angle for the file:

- `Single Responsibility Principle`: auth_service owns auth business logic, not HTTP routing.
- `Dependency Inversion Principle`: fraud handling can be injected using `fraud_service`.

---

### Segment 4: Authentication vs Authorization

File:
`app/api/deps.py`

This file is perfect for explaining the difference between identity and permission.

#### Code block: get current user

```python
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(credentials)

    try:
        payload = verify_access_token(token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    user = db.query(User).filter(User.id == payload.sub).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if user.account_status != "active":
        raise HTTPException(status_code=403, detail=f"Account is {user.account_status}")
    return user
```

What to say:

> This is authentication. It checks the bearer token, decodes it, loads the user, and verifies the account is active.

#### Code block: get current session

```python
def get_current_session(... ) -> tuple[User, SessionModel]:
    token = _extract_token(credentials)
    payload = verify_access_token(token)

    token_hash = hash_token(token)
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.access_token_hash == token_hash,
            SessionModel.is_active.is_(True),
            SessionModel.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    ...
```

What to say:

> This is stricter than normal authentication because it checks whether the session is still alive in the database. That is how logout and revocation are enforced.

Likely questions:

- Why not use `get_current_session` everywhere?
Answer: because it adds a DB liveness check each time. We reserve it for operations where immediate revocation matters most.

#### Code block: analyst/admin authorization

```python
_SCOPE_RANK: dict[str, int] = {
    SCOPE_READ_ONLY: 1,
    SCOPE_TRANSFER_AUTHORIZED: 2,
    SCOPE_MFA_ELEVATED: 3,
    SCOPE_ANALYST: 4,
    SCOPE_ADMIN: 5,
}

def require_analyst(... ) -> None:
    token = _extract_token(credentials)
    payload = verify_access_token(token)
    if _highest_rank(payload.scopes) < _SCOPE_RANK[SCOPE_ANALYST]:
        raise HTTPException(
            status_code=403,
            detail="This action requires the 'analyst' or 'admin' role."
        )
```

What to say:

> This is authorization, not authentication. A person may be logged in and still be denied because they do not have enough privilege for the action.

Best defense sentence:

> Being authenticated is necessary, but not sufficient.

SOLID angle:

- `Single Responsibility Principle`: dependency functions encapsulate reusable security checks.
- `Open/Closed Principle`: new role gates can be added without changing every route.

---

### Segment 5: Fraud Engine and SOLID Principles

File:
`app/services/fraud_service.py`

This is the best file to defend your understanding of SOLID.

#### Code block: common rule contract

```python
class IFraudRule(Protocol):
    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        ...
```

What to say:

> This protocol defines the common behavior every fraud rule must follow. Each rule receives the same input type and either returns a result or returns nothing if it does not apply.

Why it matters:

- New rules can be added consistently.
- The engine depends on a contract, not on one hardcoded rule implementation.

SOLID mapping:

- `Interface Segregation`: rules only implement the minimal interface they need.
- `Dependency Inversion`: the engine depends on the abstraction `IFraudRule`.

#### Code block: one concrete rule

```python
class DeviceAnomalyRule:
    SCORE_DELTA = 35

    def evaluate(self, db: Session, data: FraudRuleInput) -> Optional[RuleResult]:
        if not data.device_fingerprint:
            return None
        known = (
            db.query(KnownDevice)
            .filter(
                KnownDevice.user_id == data.user_id,
                KnownDevice.device_fingerprint == data.device_fingerprint,
            )
            .first()
        )
        if known is not None:
            return None
        return RuleResult(
            score_delta=self.SCORE_DELTA,
            severity="medium",
            alert_type="device_change",
            description="Login or transaction from an unknown device fingerprint",
            triggered_key="unknown_device",
            extra={"device_fingerprint": data.device_fingerprint},
        )
```

What to say:

> This rule checks whether the device fingerprint is already known for the user. If it is new, the rule contributes risk to the final fraud score.

Why this is good:

- The rule is small and explainable.
- It can be tested independently.
- It does one thing well.

SOLID mapping:

- `Single Responsibility`: this class only evaluates device anomaly logic.

#### Code block: engine aggregation

```python
class FraudRuleEngine:
    def __init__(self, rules: Optional[list[IFraudRule]] = None):
        self._rules = rules or [
            LocationRule(),
            VelocityRule(),
            LargeAmountRule(),
            DeviceAnomalyRule(),
            PatternAnomalyRule(),
        ]

    def evaluate(self, db: Session, data: FraudRuleInput) -> FraudEvaluationResult:
        total_score = 0
        triggered: dict[str, int] = {}
        descriptions: list[str] = []

        for rule in self._rules:
            result = rule.evaluate(db, data)
            if result is None:
                continue
            total_score += result.score_delta
            triggered[result.triggered_key] = result.score_delta
            descriptions.append(result.description)
```

What to say:

> The engine is closed for modification but open for extension. To add a new fraud idea, we create another rule class and plug it into the engine. We do not have to rewrite the engine itself.

SOLID mapping:

- `Open/Closed Principle`: add rules without redesigning the engine.

#### Code block: facade service

```python
class FraudService:
    def __init__(self, engine: Optional[FraudRuleEngine] = None,
                 alert_service: Optional[FraudAlertService] = None):
        self._engine = engine or FraudRuleEngine()
        self._alert_service = alert_service or FraudAlertService()

    def evaluate(self, db: Session, data: FraudRuleInput, *,
                 create_alert_if_required: bool = True,
                 commit_alert: bool = True) -> tuple[FraudEvaluationResult, Optional[FraudAlert]]:
        result = self._engine.evaluate(db, data)
        ...
```

What to say:

> This facade coordinates the rule engine and alert creation service. The engine decides risk. The alert service persists alerts. That separation improves clarity and maintainability.

Likely questions:

- Why not create alerts directly inside each rule?
Answer: because rules should evaluate risk, not perform persistence side effects.

---

### Segment 6: Transaction State Machine and Auditability

File:
`app/services/transaction_service.py`

This segment shows that the system treats transactions as controlled state transitions.

#### Code block: legal state transitions

```python
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"processing", "failed", "blocked"},
    "processing": {"completed", "failed"},
    "flagged": {"blocked", "pending"},
    "completed": set(),
    "failed": set(),
    "blocked": set(),
}

def _transition(txn: Transaction, new_status: str) -> None:
    allowed = _VALID_TRANSITIONS.get(txn.status, set())
    if new_status not in allowed:
        raise TransactionStateError(
            f"Cannot transition transaction from '{txn.status}' to '{new_status}'"
        )
    txn.status = new_status
```

What to say:

> We model transaction progression as a state machine. That prevents illegal jumps, such as taking a completed transaction back into processing.

Why this matters:

- protects consistency
- reduces hidden bugs
- makes the lifecycle explainable

Likely questions:

- Why use a state machine instead of simple updates?
Answer: because financial workflows have legal transitions and terminal states that should be enforced explicitly.

#### Code block: fraud-first transaction creation

```python
fraud_result, fraud_alert = _fraud_service.evaluate(
    db,
    fraud_input,
    create_alert_if_required=True,
    commit_alert=False,
)

if fraud_result.action == "block":
    txn = Transaction(
        user_id=user_id,
        ...
        status="blocked",
        risk_score=fraud_result.score,
        fraud_check_status="blocked",
    )
    ...
    db.commit()
    raise TransactionBlockedError("Transaction blocked by security policy")
```

What to say:

> Before the transaction is treated as processable, the fraud engine decides whether it should proceed, be flagged, or be blocked. That means risk evaluation is part of the business workflow, not an afterthought.

#### Code block: behavior training only after confirmed success

```python
update_behavior_pattern(
    db,
    user_id=user_id,
    amount=txn.amount,
    location_country=txn.location_country,
    location_city=txn.location_city,
    device_fingerprint=txn.device_fingerprint,
    commit=False,
)
```

What to say:

> We only update behavioral baselines after a transaction is completed successfully. We intentionally do not learn from pending, flagged, or blocked events because that could train fraud into the normal profile.

#### Code block: audit logging helper

```python
def _build_audit_log(
    user_id: uuid.UUID,
    action: str,
    entity_id: uuid.UUID,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    ...
) -> AuditLog:
    return AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old_values,
        new_values=new_values,
        ...
    )
```

What to say:

> For every important transaction event, we create an audit record showing what changed, who initiated it, and whether it succeeded. This is essential in a critical financial system.

SOLID angle:

- `Single Responsibility`: audit log builder focuses on audit object creation.
- `Single Responsibility`: transition helper focuses on legal state changes.

---

### Segment 7: MFA Setup and Verification Logic

File:
`app/services/mfa_service.py`

#### Code block: setup without immediate activation

```python
def setup_mfa(db: Session, user: User) -> MFASetupResponse:
    existing = (
        db.query(MFASecret)
        .filter(MFASecret.user_id == user.id, MFASecret.mfa_type == "totp")
        .all()
    )
    for old in existing:
        old.is_active = False

    secret_b32 = generate_totp_secret()
    uri = get_totp_uri(secret_b32, user.email)
    plaintext_codes, hashed_codes = generate_backup_codes()

    mfa_secret = MFASecret(
        user_id=user.id,
        mfa_type="totp",
        secret_encrypted=encrypt_totp_secret(secret_b32),
        backup_codes_encrypted=encrypt_backup_codes(hashed_codes),
        is_active=True,
    )
    db.add(mfa_secret)
    db.commit()
```

What to say:

> Setup generates the secret and recovery codes, encrypts them, and stores them safely. But setup does not yet enable MFA on the account.

#### Code block: confirm before activation

```python
def confirm_mfa_setup(db: Session, user: User, code: str) -> bool:
    mfa_secret = get_active_mfa_secret(db, user.id)
    ...
    if not verify_totp_strict(secret_b32, code):
        raise ValueError("Invalid TOTP code. Make sure your authenticator app is synced.")

    user.mfa_enabled = True
    mfa_secret.last_used = datetime.now(timezone.utc)
    db.commit()
    return True
```

What to say:

> We only activate MFA after the user proves they successfully enrolled the authenticator app. This avoids locking users out because of a bad scan or configuration mistake.

#### Code block: disable requires proof

```python
def disable_mfa(db: Session, user: User, code: str) -> bool:
    mfa_secret = get_active_mfa_secret(db, user.id)
    ...
    if not verify_totp(secret_b32, code):
        raise ValueError("Invalid TOTP code â€” MFA not disabled")

    mfa_secret.is_active = False
    user.mfa_enabled = False
    db.commit()
    return True
```

What to say:

> A stolen session token alone is not enough to disable MFA. The user must still present a valid second factor. This is a very important security boundary.

---

### Segment 8: Suggested Backend Teaching Order for Your Defense

Present the backend in this exact sequence:

1. `app/main.py`
2. `app/core/config.py`
3. `app/models/user.py`
4. `app/schemas/user.py`
5. `app/schemas/auth.py`
6. `app/core/security.py`
7. `app/api/deps.py`
8. `app/services/auth_service.py`
9. `app/services/mfa_service.py`
10. `app/services/fraud_service.py`
11. `app/services/transaction_service.py`
12. `app/api/auth_router.py`
13. `app/api/transaction_router.py`
14. `app/api/fraud_router.py`
15. `app/api/admin_router.py`
16. `tests/*`

Why this order works:

- It starts with system structure.
- Then it shows data and validation.
- Then it explains security primitives.
- Then it shows business workflows.
- Then it ends with HTTP exposure and proof through tests.

---

### Segment 9: Fast Oral Script You Can Reuse

Use this script whenever someone points at a backend code block:

> This code sits at the boundary between user input and system trust.  
> First, it validates the shape of the data.  
> Second, it applies the business or security rule.  
> Third, it either rejects invalid behavior early or passes safe data deeper into the system.  
> We designed it this way to keep the application secure, explainable, and maintainable.

Use this script for SOLID questions:

> We followed SOLID mainly by separating responsibilities.  
> Schemas validate input, routers handle HTTP, services handle business logic, security utilities handle cryptographic operations, and rule classes isolate fraud checks.  
> That makes the code easier to test, extend, and reason about under pressure.

---

## 14. Backend Code Defense Segments Part 2

This part continues the same backend-first tutorial style, but with even more emphasis on what to say aloud while pointing at the code.

### Segment 10: Backend Entry Point and System Composition

File:
`app/main.py`

This is the file you should use when someone asks:

- "Where does the backend actually start?"
- "How are all the modules wired together?"
- "Where is middleware configured?"

#### Code block: application creation and router mounting

```python
app = FastAPI(
    title="Secure Banking API",
    description=(
        "A production-grade secure banking backend with fraud detection, "
        "JWT authentication, MFA support, and full audit logging."
    ),
    version="1.0.0",
)

app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(transaction_router, prefix=settings.API_V1_STR)
app.include_router(fraud_router, prefix=settings.API_V1_STR)
app.include_router(audit_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(user_router, prefix=settings.API_V1_STR)
```

What this does:

- Creates the FastAPI app instance.
- Defines global metadata such as name and version.
- Mounts all route groups under the shared API prefix.

What to say:

> This is the composition root of the backend. It does not contain business logic itself. Its responsibility is to assemble the application by creating the app object and attaching all routers in one place.

Longer explanation you can say to a beginner:

> Think of this file like the control room of the backend. The business logic lives elsewhere, but this is where we connect all the departments together so the system can actually run as one application.

Why this is good design:

- It keeps startup logic centralized.
- It prevents business rules from being scattered into the entry file.
- It makes the backend easier to reason about and easier to test.

Likely questions:

- Why not write login logic directly here?
Answer: because this file should compose the system, not implement the system.

#### Code block: security middleware

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)
```

What this does:

- `CORSMiddleware` controls which frontend origins may call the backend.
- `TrustedHostMiddleware` helps reject suspicious host headers.

What to say:

> Middleware is logic that wraps every request before it reaches the route handlers. We use it for cross-cutting security concerns so we do not have to duplicate the same protection in every endpoint.

Good defense sentence:

> We put cross-cutting protections in middleware, not in individual routes, because the rule applies system-wide.

Likely questions:

- Why is wildcard host/origin acceptable in development but not production?
Answer: because production should whitelist only trusted domains to reduce abuse and misrouting risk.

#### Code block: health endpoints

```python
@app.get("/")
def root() -> dict:
    return {
        "status": "healthy",
        "service": "Secure Banking API",
        "version": "1.0.0",
    }

@app.get("/health")
def health() -> dict:
    return {
        "status": "healthy",
        "database": "connected",
        "fraud_engine": "active",
    }
```

What to say:

> These endpoints support operational monitoring. In a critical system, proving that the service is alive and healthy is part of the engineering story, not just a convenience.

---

### Segment 11: Database Session Management

File:
`app/models/database.py`

This is the file to use when someone asks:

- "How does the app talk to the database?"
- "How are connections managed?"
- "What is dependency-injected into the routes?"

#### Code block: engine and session factory

```python
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    connect_args={"sslmode": settings.DATABASE_SSLMODE}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
```

What this does:

- Creates the DB engine.
- Enables connection pooling.
- Configures secure transport through SSL mode.
- Creates a session factory used throughout the app.

What to say:

> This file abstracts the low-level database connection details. Rather than opening raw connections everywhere, we define one engine and one session factory, then reuse them consistently through dependency injection.

How to explain to a beginner:

> Instead of every part of the app making its own ad hoc database connection, we created one standardized way to talk to the database. That makes the system safer and more efficient.

#### Code block: request-scoped DB session

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

What this does:

- Opens a database session for the request.
- Yields it to the route/service layer.
- Guarantees cleanup after the request finishes.

What to say:

> This gives each request a clean database session and guarantees it is closed afterward. That prevents connection leaks and keeps database usage disciplined.

Likely questions:

- Why `yield` instead of returning the session?
Answer: because `yield` allows FastAPI to run cleanup logic after the request completes.

SOLID angle:

- `Single Responsibility Principle`: this file handles DB access setup only.

---

### Segment 12: Explaining the Data Model Like a Story

File:
`app/models/user.py`

This file is long, so do not teach it table by table in random order. Teach it as a business story.

Use this narrative:

1. A `User` owns an account.
2. A `User` can have many `Session` records.
3. A `User` can have MFA secrets.
4. A `User` can perform many transactions.
5. Transactions can trigger fraud alerts.
6. Important actions become audit logs.
7. Device and behavior history improve fraud decisions.

#### Code block: user identity and role model

```python
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user", server_default="user", nullable=False)
    account_status = Column(String(20), default="active", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'locked', 'closed')",
            name="account_status_check",
        ),
        CheckConstraint(
            "role IN ('user', 'analyst', 'admin')",
            name="user_role_check",
        ),
    )
```

What to say:

> This is the core identity record. It stores who the user is, how they authenticate, what role they hold, and whether the account is currently active or restricted.

The crucial line to emphasize:

> We enforce allowed role and status values not only in application code but also in the database through check constraints.

Why that matters:

- The backend becomes safer even if a coding mistake occurs elsewhere.
- The database itself rejects invalid states.

Likely questions:

- Why put these constraints in the database too?
Answer: because the database is the final source of truth and should defend its own integrity.

#### Code block: session model

```python
class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_token_hash = Column(String(255), nullable=False)
    refresh_token_hash = Column(String(255))
    device_fingerprint = Column(String(255))
    ip_address = Column(INET)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
```

What to say:

> This table is why our JWT system is operationally controllable. The token may be stateless, but the session is stateful. That lets us revoke sessions, track device context, and support secure logout.

#### Code block: transaction and fraud models

```python
class Transaction(Base):
    __tablename__ = "transactions"
    ...
    status = Column(String(20), default="pending")
    risk_score = Column(Integer)
    fraud_check_status = Column(String(20), default="pending")

class FraudAlert(Base):
    __tablename__ = "fraud_alerts"
    ...
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), default="open")
```

What to say:

> We modeled transactions and fraud alerts as separate but linked entities because a transaction is the business event, while a fraud alert is the operational investigation record created around risk.

#### Code block: audit log model

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"
    ...
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    old_values = Column(JSONB)
    new_values = Column(JSONB)
    success = Column(Boolean, nullable=False)
```

What to say:

> This table exists so we can answer: who did what, to which entity, when, and with what outcome. In a critical system, that kind of traceability is essential.

How to explain simply:

> Audit logs are the memory of the system.

---

### Segment 13: Admin Governance Logic

File:
`app/services/admin_service.py`

Use this when discussing governance, operational control, and internal controls.

#### Code block: admin audit helper

```python
def _audit(
    db: Session,
    admin_id: uuid.UUID,
    action: str,
    target_user_id: uuid.UUID,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    db.add(AuditLog(
        user_id=admin_id,
        action=action,
        entity_type="user",
        entity_id=target_user_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        success=True,
    ))
```

What to say:

> Every privileged admin action writes an audit record. That means administrator power is traceable, reviewable, and accountable.

Good defense sentence:

> In banking, admin functionality without auditability is a governance failure.

#### Code block: suspend/lock/close and revoke sessions

```python
def update_account_status(...):
    if new_status not in VALID_STATUSES:
        raise AdminInvalidStatusError(...)
    if admin_id == target_user_id:
        raise AdminSelfModifyError("Admins cannot change their own account status")

    user = get_user(db, target_user_id)
    old_status = user.account_status
    user.account_status = new_status

    if new_status == "active":
        user.locked_until = None
        user.failed_login_attempts = 0

    sessions_invalidated = 0
    if new_status != "active":
        sessions_invalidated = invalidate_user_sessions(db, target_user_id, commit=False)
```

What to say:

> This is a very important governance control. When an account becomes non-active, we do not just change a flag. We also invalidate active sessions so the user cannot continue operating under already-issued tokens.

Likely question:

- Why prevent admins from modifying themselves?
Answer: to reduce accidental lockout, abuse, and unsafe self-escalation/self-demotion scenarios.

#### Code block: role changes

```python
def update_user_role(...):
    if new_role not in VALID_ROLES:
        raise AdminInvalidStatusError(...)
    if admin_id == target_user_id:
        raise AdminSelfModifyError("Admins cannot change their own role")

    user = get_user(db, target_user_id)
    old_role = user.role
    user.role = new_role
    ...
    db.commit()
```

What to say:

> Role management is separated from account status because privilege changes and account disabling are different control actions with different side effects.

Important nuance to say:

> Role changes take effect on token refresh, not instantly, because our design avoids a full session revocation check on every single request. If immediate enforcement is needed, the admin can also invalidate sessions.

That answer sounds mature and realistic.

#### Code block: demo system policy store

```python
_SYSTEM_POLICY_SETTINGS: dict[str, Any] = {
    "daily_withdrawal_limit": 10_000_000,
    "global_rate_limit": 50_000,
    "multi_sig_internal_ops": True,
    "forced_24h_password_cycle": False,
    "updated_at": None,
}
```

What to say:

> This policy store is intentionally a demo implementation for the admin console workflow. In production we would move this into a dedicated persistent configuration table or configuration service.

Why this is a strong answer:

- It shows honesty.
- It shows you know the difference between prototype and production architecture.

---

### Segment 14: Device Intelligence

File:
`app/services/device_service.py`

This is a good file to use when someone asks how fraud scoring becomes more intelligent over time.

#### Code block: device upsert logic

```python
def register_device(
    db: Session,
    user_id: uuid.UUID,
    device_fingerprint: Optional[str],
    *,
    commit: bool = False,
) -> Optional[KnownDevice]:
    if not device_fingerprint:
        return None

    existing = (
        db.query(KnownDevice)
        .filter(
            KnownDevice.user_id == user_id,
            KnownDevice.device_fingerprint == device_fingerprint,
        )
        .first()
    )

    if existing:
        existing.last_seen = now
        device = existing
    else:
        device = KnownDevice(
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            is_trusted=False,
            first_seen=now,
            last_seen=now,
        )
        db.add(device)
```

What to say:

> This service turns repeated device use into knowledge. Without it, every login would look like a new-device anomaly forever. With it, the system gradually learns which devices are normal for each user.

How to explain to a beginner:

> The first time the system sees a device, it is suspicious. The second time, it becomes context. This file is what creates that memory.

Likely questions:

- Why not insert a new row every time?
Answer: because the goal is device identity history, not noisy duplicates.

#### Code block: remove device

```python
def remove_device(db: Session, user_id: uuid.UUID, device_id: uuid.UUID) -> bool:
    device = (
        db.query(KnownDevice)
        .filter(
            KnownDevice.id == device_id,
            KnownDevice.user_id == user_id,
        )
        .first()
    )
    if not device:
        return False

    db.delete(device)
    db.commit()
    return True
```

What to say:

> Removing a device is a user-driven security action. After removal, the next login from that device becomes suspicious again, which is exactly what we want if the device is no longer trusted.

---

### Segment 15: Behavioral Baseline Learning

File:
`app/services/behavior_service.py`

This is one of the best files for demonstrating thoughtful engineering, because it shows that the system learns carefully, not blindly.

#### Code block: EMA helper

```python
def _ema(current: Decimal, new_value: Decimal, alpha: float = EMA_ALPHA) -> Decimal:
    result = Decimal(str(alpha)) * new_value + Decimal(str(1 - alpha)) * current
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

What to say:

> We use an exponential moving average rather than a simple average because recent behavior should matter more than very old behavior. That makes the baseline adaptive without becoming unstable.

How to explain simply:

> This lets the system learn a user's new normal gradually instead of being permanently dominated by old history.

#### Code block: bounded recent context

```python
def _update_bounded_list(existing_value: Optional[Any], new_entry: Optional[str]) -> list[str]:
    ...
    if new_entry in items:
        items.remove(new_entry)
    items.insert(0, new_entry)
    items = items[:MAX_RECENT_ENTRIES]
    return items
```

What to say:

> We keep recent locations and devices as bounded, de-duplicated lists. That gives the fraud engine useful explainable context without letting those lists grow forever.

#### Code block: only train from completed transactions

```python
def update_behavior_pattern(...):
    """
    Must only be called when txn.status == 'completed'. Pending or flagged
    amounts must not be learned from â€” they could be fraud probing attempts.
    """
```

What to say:

> This is a very important design choice. We only learn from trusted completed events. If we learned from flagged or blocked events, the system could normalize fraudulent behavior over time.

This is a very strong interview answer.

#### Code block: first baseline vs update path

```python
if pattern is None:
    pattern = UserBehaviorPattern(
        user_id=user_id,
        average_transaction_amount=amount_decimal,
        max_transaction_amount=amount_decimal,
        typical_transaction_frequency=1,
        typical_locations=[location_label] if location_label else [],
        typical_devices=[device_fingerprint] if device_fingerprint else [],
        last_updated=now,
    )
else:
    pattern.average_transaction_amount = _ema(current_avg, amount_decimal)
    ...
```

What to say:

> On the first trusted transaction, we create the baseline. On later trusted transactions, we refine that baseline. This is a controlled learning process rather than a black-box model.

---

### Segment 16: Rate Limiting as a Security Control

File:
`app/core/rate_limiter.py`

This file helps you answer operational security questions.

#### Code block: sliding window logic

```python
def check_rate_limit(
    request: Request,
    endpoint_name: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    key = _get_client_key(request, endpoint_name)
    now = time.monotonic()
    cutoff = now - window_seconds

    with _locks[key]:
        timestamps = _store[key]

        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            retry_after = int(timestamps[0] - cutoff) + 1
            raise HTTPException(status_code=429, ...)

        timestamps.append(now)
```

What to say:

> This implements a sliding-window rate limiter. Instead of counting requests in rough fixed buckets, it continuously checks the recent time window, which makes burst abuse harder.

How to explain simply:

> We keep a short memory of recent requests. If too many happen too quickly, the request is rejected.

Likely questions:

- Why sliding window instead of fixed window?
Answer: because fixed windows allow burst behavior at boundaries, while sliding windows are more accurate for abuse prevention.

#### Code block: endpoint-specific limiters

```python
login_rate_limiter = RateLimiter(
    endpoint_name="login",
    max_requests=5,
    window_seconds=60,
)

mfa_verify_rate_limiter = RateLimiter(
    endpoint_name="mfa_verify",
    max_requests=5,
    window_seconds=300,
)

register_rate_limiter = RateLimiter(
    endpoint_name="register",
    max_requests=3,
    window_seconds=3600,
)
```

What to say:

> We tailored limits to the risk of each endpoint. Login and MFA verification are brute-force targets, while registration is vulnerable to account farming. So we applied endpoint-specific policies instead of one global limit.

Good honest limitation answer:

> This implementation is in-memory and best suited for single-process deployment. In production, Redis or another shared store would be the natural next step.

---

### Segment 17: TOTP Internals and Why They Matter

File:
`app/core/totp.py`

This file is ideal for showing deep understanding.

#### Code block: encrypting the TOTP secret

```python
def _get_fernet() -> Fernet:
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt_totp_secret(plaintext_secret: str) -> bytes:
    return _get_fernet().encrypt(plaintext_secret.encode())

def decrypt_totp_secret(encrypted_secret: bytes) -> str:
    return _get_fernet().decrypt(encrypted_secret).decode()
```

What to say:

> TOTP secrets cannot be hashed like passwords because the server must recover them to verify codes. So instead of hashing, we encrypt them at rest.

That sentence is extremely important.

Likely question:

- Why not hash the TOTP secret?
Answer: because verification requires the server to derive the expected code from the original secret.

#### Code block: provisioning URI

```python
def get_totp_uri(secret: str, email: str, issuer: str = "SecureBankPro") -> str:
    from urllib.parse import quote
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}"
        f"?secret={quote(secret)}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits=6"
        f"&period=30"
    )
```

What to say:

> This URI is what authenticator apps scan. It packages the issuer, account, secret, algorithm, and timing settings into the standard format understood by apps like Google Authenticator.

#### Code block: core TOTP verification

```python
def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    secret_bytes = base64.b32decode(_normalize_base32_secret(secret_b32))
    code_int = int(code)
    ...
    t = int(time.time()) // 30
    return any(
        _hotp(secret_bytes, t + delta) == code_int
        for delta in range(-window, window + 1)
    )
```

What to say:

> TOTP is time-based OTP. The secret and the current time window generate the expected code. We allow a small drift window so minor device/server clock differences do not lock out legitimate users.

How to explain simply:

> The phone and the server independently do the same time-based calculation. If the results match, the code is accepted.

#### Code block: backup code consumption

```python
def verify_and_consume_backup_code(code: str, encrypted_codes: bytes) -> Optional[bytes]:
    code_hash = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    hashed_codes = decrypt_backup_codes(encrypted_codes)
    if code_hash not in hashed_codes:
        return None
    hashed_codes.remove(code_hash)
    return encrypt_backup_codes(hashed_codes)
```

What to say:

> Backup codes are single-use recovery credentials. Once used, they are removed from the stored set so they cannot be replayed.

---

### Segment 18: Explaining the Router Layer Clearly

Files:

- `app/api/auth_router.py`
- `app/api/transaction_router.py`
- `app/api/fraud_router.py`
- `app/api/admin_router.py`
- `app/api/audit_router.py`
- `app/api/user_router.py`

You do not need to read every route line by line. Instead use this standard explanation:

> The router layer is the HTTP translation layer.  
> It receives requests, applies dependencies like authentication or role checks, calls the service layer, and converts service outcomes into clear HTTP responses.

Then give an example.

#### Example code block: auth route delegates to service

```python
@router.post("/login", response_model=LoginResponse)
def login(data: UserLogin, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ...
    response = auth_service.login(
        db,
        data,
        ip_address=ip,
        user_agent=user_agent,
        device_fingerprint=device_fingerprint,
        location_country=location_country,
        location_city=location_city,
    )
```

What to say:

> The route does not contain deep login logic. It collects HTTP context like request headers, then delegates the business decision to the auth service.

#### Example code block: analyst-only route

```python
@router.post(
    "/{transaction_id}/block",
    response_model=TransactionResponse,
    dependencies=[Depends(require_analyst)],
)
def block(...):
    ...
```

What to say:

> This route is a good example of layered security. The route is authenticated, then separately authorized for analyst/admin scope before the business action is allowed.

Good interview sentence:

> The router enforces the boundary; the service enforces the workflow.

---

### Segment 19: Tests as Proof, Not Decoration

Files:

- `tests/test_api.py`
- `tests/test_mfa.py`
- `tests/test_fraud_scoring.py`
- other backend tests

This section is crucial because many students talk about features but not verification.

#### Code block: router testing strategy

```python
test_app = FastAPI(title="Test Banking API")
test_app.include_router(auth_router, prefix=PREFIX)
test_app.include_router(transaction_router, prefix=PREFIX)
test_app.include_router(fraud_router, prefix=PREFIX)
test_app.include_router(audit_router, prefix=PREFIX)
```

What to say:

> We test the real router modules in isolation by building a dedicated test app. That lets us verify endpoint behavior without needing the full production runtime.

#### Code block: security boundary example

```python
def test_block_requires_analyst_scope_not_just_authentication(self, mock_db, alice):
    def _deny():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Insufficient permissions. "
                "This action requires the 'analyst' or 'admin' role."
            ),
        )
```

What to say:

> This kind of test is especially important because it proves we did not only test happy paths. We tested security boundaries, such as the difference between being logged in and being sufficiently authorized.

#### Code block: MFA token-type safety

```python
def test_mfa_pending_token_rejected_by_verify_access(self):
    from app.core.security import create_mfa_pending_token, verify_access_token
    uid = uuid.uuid4()
    mfa_token, _ = create_mfa_pending_token(uid)
    with pytest.raises(pyjwt.InvalidTokenError):
        verify_access_token(mfa_token)
```

What to say:

> This test proves that a token created for MFA cannot be reused as a normal API token. That is a direct security guarantee, not just a feature test.

Best sentence for a panel:

> Our tests validate both functionality and trust boundaries.

---

### Segment 20: Migrations and Schema Evolution

Files:

- `alembic/env.py`
- `alembic/versions/*.py`

What to say:

> We used migrations because serious systems change over time. A schema is not static, so database evolution must be versioned, repeatable, and reversible.

How to explain simply:

> Migrations are the history of how the database grew safely.

Likely questions:

- Why not just recreate the database each time?
Answer: because real systems contain live data and schema changes must preserve it.

Strong maturity sentence:

> Using migrations shows we treated persistence as an evolving production concern, not a temporary classroom artifact.

---

### Segment 21: Best Spoken Backend Walkthrough

If you need to present the backend in a strong, smooth order, say it like this:

> We begin with `app/main.py`, where the FastAPI application is composed and protected by middleware.  
> Then we move into `database.py` and the ORM models, which define how users, sessions, transactions, fraud alerts, and audit logs are stored.  
> After that, we show Pydantic schemas, which validate incoming data before the business layer sees it.  
> Next we explain `security.py`, where passwords are hashed and token types are defined.  
> Then we cover `deps.py`, which separates authentication from authorization.  
> After that we move into the service layer, especially `auth_service.py`, `mfa_service.py`, `fraud_service.py`, and `transaction_service.py`, because that is where the core banking and security workflows live.  
> Finally, we show the router layer, which exposes those workflows as HTTP endpoints, and then the tests, which prove those security boundaries actually hold.

This is a very good master's defense flow.

---

### Segment 22: Strong "What To Say" Lines You Can Reuse

Use these short sentences when you feel under pressure.

#### On validation

> We reject unsafe or malformed input at the schema layer before it reaches business logic.

#### On password security

> We never store plaintext passwords; we store bcrypt hashes and verify against them.

#### On JWT plus sessions

> JWT gives efficient authentication, while the session table gives revocation and operational control.

#### On MFA

> MFA is implemented as a separate proof step, not as a UI decoration after login.

#### On fraud

> Fraud scoring is explainable because each rule contributes a clear, auditable part of the decision.

#### On state machines

> Transaction progression is modeled as legal transitions, not arbitrary updates.

#### On audit logs

> Audit logging turns sensitive actions into evidence.

#### On SOLID

> We used SOLID by giving each layer one main job and making important components reusable and extensible.

#### On tests

> We tested both features and security boundaries, because a secure system is not proven by UI success alone.

---

### Segment 23: Best Next Move

The backend part of this guide is now structured enough to teach someone step by step and defend the code confidently in front of a panel.

The strongest next extension would be one of these:

1. Convert the backend sections into a full spoken viva script.
2. Create a "one file at a time" backend lesson plan with checkpoints and likely follow-up questions after each file.
3. Move to the frontend and build the same code-backed tutorial format there.

---

## 15. Frontend Code Defense Segments

This section explains the frontend in the same teaching-and-defense format as the backend.

The best way to present the frontend is this:

1. Show how the browser boots the app.
2. Show how routing is organized.
3. Show how authentication state is managed.
4. Show how API calls are centralized.
5. Show how protected routes work.
6. Show how the UI changes by role.
7. Then show page examples: login, dashboard, transactions, analyst workspace, admin console.

The key message to keep repeating is:

> The frontend is not the primary security boundary, but it is the primary user-experience boundary.

That is a strong sentence because it shows you understand the difference between security enforcement and interface design.

### Segment 1: Frontend Entry Point

File:
`secure-bank-frontend/src/main.tsx`

#### Code block: app bootstrap

```tsx
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <App />,
)
```

What this does:

- Loads global styles.
- Mounts the React application into the browser DOM.
- Uses `App` as the root component.

What to say:

> This is the frontend bootstrap file. Its responsibility is very small: start the React application and attach it to the browser page.

How to explain to a beginner:

> This is the point where the browser stops being a blank HTML page and starts becoming our application.

Why this matters:

- It keeps startup clean.
- It prevents app logic from being mixed with browser mounting logic.

---

### Segment 2: Route Tree and Application Structure

File:
`secure-bank-frontend/src/App.tsx`

This is the main frontend composition file, just like `app/main.py` is for the backend.

#### Code block: browser router + auth provider

```tsx
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          ...
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
```

What this does:

- Wraps the whole app in React Router.
- Wraps the whole app in `AuthProvider`, so all pages can access authentication state.

What to say:

> This file composes the frontend application. It connects routing with authentication state and becomes the top-level structure through which all pages are rendered.

Good teaching sentence:

> If the backend composition root is `app/main.py`, then the frontend composition root is `App.tsx`.

#### Code block: public vs protected routes

```tsx
<Route path="/login" element={<LoginPage />} />
<Route path="/register" element={<RegisterPage />} />
<Route path="/mfa/verify" element={<MfaVerifyPage />} />

<Route
  path="/dashboard"
  element={
    <RequireAuth>
      <DashboardPage />
    </RequireAuth>
  }
/>
```

What this does:

- Keeps login, register, and MFA verify public.
- Protects dashboard and authenticated pages behind `RequireAuth`.

What to say:

> The route tree expresses the trust model of the frontend. Public pages are accessible to everyone, while operational pages are wrapped by route guards that check the current authentication state.

Important nuance:

> `/mfa/verify` is intentionally public because the credential for that step is the `mfa_token` in the request body, not an already-established session.

That mirrors the backend explanation nicely.

#### Code block: role-specific routes

```tsx
<Route
  path="/analyst/fraud"
  element={
    <RequireAuth role="analyst">
      <FraudWorkspacePage />
    </RequireAuth>
  }
/>

<Route
  path="/admin/users"
  element={
    <RequireAuth role="admin">
      <AdminControlCenterPage />
    </RequireAuth>
  }
/>
```

What to say:

> The frontend reflects the backend role hierarchy. Analysts get specialized investigation tools, while admins get governance and control features.

Likely question:

- Why enforce roles in the frontend if the backend already does?
Answer: because frontend checks improve navigation and user experience, while the backend remains the true enforcement layer.

---

### Segment 3: Global Authentication State

File:
`secure-bank-frontend/src/contexts/AuthContext.tsx`

This is one of the most important frontend files.

#### Code block: auth state shape

```tsx
interface AuthState {
  user: UserResponse | null
  isAuthenticated: boolean
  isLoading: boolean
  mfaPending: {
    mfaToken: string
    email: string
    userId: string
  } | null
  riskFlagged: boolean
}
```

What this does:

- Stores the authenticated user.
- Tracks whether the app is still hydrating the session.
- Tracks pending MFA state.
- Tracks whether a login was flagged by the fraud engine.

What to say:

> This context is the single source of truth for frontend authentication state. It lets all pages read and react to the same session information without duplicating auth logic.

How to explain simply:

> Instead of every page trying to figure out whether the user is logged in, we created one shared place that knows.

#### Code block: reducer actions

```tsx
type AuthAction =
  | { type: 'HYDRATE_SUCCESS'; payload: UserResponse }
  | { type: 'HYDRATE_FAIL' }
  | { type: 'LOGIN_SUCCESS'; payload: { user: UserResponse; riskFlagged: boolean } }
  | { type: 'MFA_REQUIRED'; payload: { mfaToken: string; email: string; userId: string } }
  | { type: 'MFA_COMPLETE'; payload: { user: UserResponse; riskFlagged: boolean } }
  | { type: 'LOGOUT' }
  | { type: 'UPDATE_USER'; payload: UserResponse }
```

What to say:

> We used a reducer because authentication is stateful and event-driven. The reducer makes the auth lifecycle explicit: hydration, login, MFA-required, MFA-complete, logout, and profile update.

This is a very strong React explanation.

#### Code block: hydrate on app startup

```tsx
useEffect(() => {
  async function hydrate() {
    if (!tokenStore.hasTokens()) {
      dispatch({ type: 'HYDRATE_FAIL' })
      return
    }
    try {
      const { data } = await http.get<UserResponse>('/auth/me')
      dispatch({ type: 'HYDRATE_SUCCESS', payload: data })
    } catch {
      tokenStore.clearTokens()
      dispatch({ type: 'HYDRATE_FAIL' })
    }
  }
  hydrate()
}, [])
```

What this does:

- On startup, checks whether tokens exist.
- If they do, tries to validate them through `/auth/me`.
- If validation fails, clears them and returns to unauthenticated state.

What to say:

> The frontend does not blindly trust leftover tokens. It rehydrates by calling the backend and asking, "Is this still a valid authenticated session?"

This is a strong line because it shows the frontend trusts the backend as the source of truth.

#### Code block: login flow

```tsx
const response = await http.post<LoginResponse>(
  '/auth/login',
  credentials,
  { validateStatus: status => status < 500 }
)

if (response.status === 202) {
  dispatch({
    type: 'MFA_REQUIRED',
    payload: {
      mfaToken: body.mfa_token!,
      email: body.email,
      userId: body.user_id,
    },
  })
  return 'mfa_required'
}
```

What to say:

> The frontend is aware that login is not always one-step. It can branch into a second-factor flow when the backend returns 202 and supplies an MFA token.

#### Code block: MFA verification flow

```tsx
const response = await http.post<LoginResponse>(
  '/auth/mfa/verify',
  {
    mfa_token: state.mfaPending.mfaToken,
    code,
  },
  { validateStatus: status => status < 500 }
)
```

What to say:

> The MFA page is not using an access token because the user is not fully logged in yet. Instead, it uses the backend-issued `mfa_token`, which is the temporary credential for completing the login process.

#### Code block: role hierarchy on frontend

```tsx
const ROLE_RANK: Record<UserRole, number> = {
  user: 1,
  analyst: 2,
  admin: 3,
}

const hasRole = useCallback(
  (role: UserRole | UserRole[]): boolean => {
    if (!state.user) return false
    const required = Array.isArray(role) ? role : [role]
    const userRank = ROLE_RANK[state.user.role]
    const minRequired = Math.min(...required.map(r => ROLE_RANK[r]))
    return userRank >= minRequired
  },
  [state.user]
)
```

What to say:

> The frontend mirrors the backend role hierarchy so navigation and route guards behave consistently. Admin automatically satisfies analyst-level UI checks.

SOLID angle:

- `Single Responsibility Principle`: AuthContext handles auth state, not page rendering.

---

### Segment 4: Token Storage Strategy

File:
`secure-bank-frontend/src/lib/token.ts`

#### Code block: in-memory storage

```tsx
let _accessToken: string | null = null
let _refreshToken: string | null = null

export const tokenStore = {
  getAccessToken(): string | null {
    return _accessToken
  },
  getRefreshToken(): string | null {
    return _refreshToken
  },
  setTokens(accessToken: string, refreshToken: string): void {
    _accessToken = accessToken
    _refreshToken = refreshToken
  },
  clearTokens(): void {
    _accessToken = null
    _refreshToken = null
  },
}
```

What this does:

- Stores tokens only in memory.
- Avoids localStorage/sessionStorage persistence.

What to say:

> We intentionally store tokens in memory instead of localStorage. That reduces exposure to token theft through XSS, which is especially important in a banking application.

Important trade-off to explain:

> The trade-off is that closing the tab logs the user out. For a financial system, that is acceptable and even desirable.

Likely question:

- Why not use localStorage for convenience?
Answer: because convenience is not the primary design goal for highly sensitive credentials.

---

### Segment 5: Central HTTP Client and Silent Refresh

File:
`secure-bank-frontend/src/lib/http.ts`

This is one of the best frontend files to defend.

#### Code block: request interceptor

```tsx
http.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  try {
    const fp = await getDeviceFingerprint()
    config.headers['X-Device-Fingerprint'] = fp
  } catch {
    // Fingerprint failure is non-fatal
  }

  return config
})
```

What this does:

- Attaches bearer token automatically.
- Attaches device fingerprint automatically.

What to say:

> Every frontend API request goes through one central client. That means token attachment and device context are handled consistently instead of being repeated page by page.

Why this matters:

- fewer mistakes
- less duplication
- consistent fraud context

#### Code block: single refresh flow

```tsx
if (isRefreshing) {
  const newToken = await enqueueRefreshSubscriber()
  config.headers.Authorization = `Bearer ${newToken}`
  return http(config)
}

config._retry = true
isRefreshing = true
```

What to say:

> This is a refresh mutex. If several requests fail at the same time because the access token expired, only one refresh request is sent. The others wait for that result instead of causing a refresh storm.

That is a strong engineering explanation.

#### Code block: refresh then retry

```tsx
const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
  refresh_token: refreshToken,
})

tokenStore.setTokens(data.access_token, data.refresh_token)
resolveRefreshQueue(data.access_token)

config.headers.Authorization = `Bearer ${data.access_token}`
return http(config)
```

What to say:

> When the access token expires, the client silently asks for a fresh token pair, updates the store, and retries the original request. This improves reliability without weakening security.

#### Code block: failed refresh handling

```tsx
tokenStore.clearTokens()
window.dispatchEvent(new CustomEvent('auth:session-expired'))
```

What to say:

> If refresh fails, the frontend treats the session as truly dead. It clears tokens and broadcasts a session-expired event so the auth context can reset state and send the user back to login.

This is a very clean architectural answer.

SOLID angle:

- `Single Responsibility Principle`: HTTP concerns are centralized here, not spread across pages.

---

### Segment 6: Device Fingerprinting in the Browser

File:
`secure-bank-frontend/src/lib/fingerprint.ts`

#### Code block: browser-signal fingerprint construction

```tsx
const components: (string | number)[] = [
  navigator.userAgent,
  navigator.language,
  navigator.languages.join(','),
  `${screen.width}x${screen.height}x${screen.colorDepth}`,
  new Date().getTimezoneOffset(),
  navigator.hardwareConcurrency ?? 0,
  navigator.maxTouchPoints ?? 0,
  navigator.platform,
  getWebGLRenderer(),
  await getCanvasFingerprint(),
]

const raw = components.join('||')
return hashString(raw)
```

What this does:

- Collects browser and device characteristics.
- Combines them into one raw string.
- Hashes them into a stable fingerprint.

What to say:

> The frontend generates a stable device fingerprint so the backend fraud engine can recognize repeated device usage. Without this, every request would look like it came from an unknown device.

How to explain simply:

> This is how the browser tells the backend, "I look like the same device as last time."

#### Code block: caching

```tsx
let _cachedFingerprint: string | null = null

export async function getDeviceFingerprint(): Promise<string> {
  if (_cachedFingerprint !== null) return _cachedFingerprint
  _cachedFingerprint = await buildFingerprint()
  return _cachedFingerprint
}
```

What to say:

> We cache the fingerprint for the session so the expensive browser work happens once, not on every API request.

Likely question:

- Why hash the fingerprint string?
Answer: because the backend needs a stable identifier, not raw browser internals exposed in plain form.

---

### Segment 7: Protected Routes

File:
`secure-bank-frontend/src/components/guards/RequireAuth.tsx`

#### Code block: route guard logic

```tsx
export function RequireAuth({ children, role }: RequireAuthProps) {
  const { isAuthenticated, isLoading, hasRole } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <LoadingScreen />
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (role !== undefined && !hasRole(role)) {
    return <Navigate to="/unauthorized" replace />
  }

  return <>{children}</>
}
```

What this does:

- Waits for hydration to finish.
- Redirects anonymous users to login.
- Redirects under-privileged users to unauthorized.
- Otherwise renders the page.

What to say:

> This component protects route access at the interface level. It improves the user experience by preventing pages from rendering briefly and then disappearing after auth checks complete.

Very strong sentence:

> The backend is the true security gate, but `RequireAuth` is the frontend traffic controller.

Likely question:

- Why preserve `location.state.from`?
Answer: so the login page can send the user back to their intended destination after successful authentication.

---

### Segment 8: Authenticated Layout and Role-Aware Navigation

File:
`secure-bank-frontend/src/components/layout/AppShell.tsx`

This file is important because it shows how role-based UX is implemented.

#### Code block: role-aware navigation config

```tsx
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', href: '/dashboard', requiredRole: null, icon: Icons.grid },
  { label: 'Transactions', href: '/transactions', requiredRole: null, icon: Icons.transactions },
  { label: 'Fraud Workspace', href: '/analyst/fraud', requiredRole: 'analyst', icon: Icons.fraud },
  { label: 'User Management', href: '/admin/users', requiredRole: 'admin', icon: Icons.users },
]
```

What this does:

- Defines nav items declaratively.
- Associates some items with required roles.

#### Code block: filtered nav

```tsx
const visibleNav = NAV_ITEMS.filter(item =>
  item.requiredRole === null || hasRole(item.requiredRole)
)
```

What to say:

> Navigation is generated from a role-aware configuration rather than hardcoded separately in every page. That makes the interface consistent and easier to maintain.

How to explain simply:

> The user only sees the tools that match their role.

#### Code block: sign out flow

```tsx
async function handleSignOut() {
  await logout()
  navigate('/login', { replace: true })
}
```

What to say:

> The layout is also the shared operational shell. It centralizes sign-out behavior and surrounds every authenticated page with a consistent navigation and identity context.

SOLID angle:

- `Single Responsibility Principle`: AppShell handles authenticated layout composition, not page-specific business logic.

---

### Segment 9: Login Page UX and Security-Aware Outcomes

File:
`secure-bank-frontend/src/pages/auth/LoginPage.tsx`

#### Code block: login result handling

```tsx
const result = await login({
  email: raw.includes('@') ? raw : undefined,
  username: raw.includes('@') ? undefined : raw,
  password: form.password,
})

if (result === 'success') {
  navigate(redirectPath, { replace: true })
  return
}
if (result === 'success_flagged') {
  window.alert('We noticed unusual activity. Please review your recent transactions.')
  navigate(redirectPath, { replace: true })
  return
}
if (result === 'mfa_required') {
  navigate('/mfa/verify', { replace: true })
  return
}
```

What this does:

- Sends either email or username depending on what the user typed.
- Handles successful login, flagged login, and MFA-required login separately.

What to say:

> The login page is not just a form. It is the UI interpreter of backend security outcomes. Different backend decisions lead to different user journeys.

Good line to use:

> Security outcomes are reflected explicitly in the user interface, not hidden.

#### Code block: blocked/locked/invalid feedback

```tsx
if (result === 'locked') {
  setError('Account temporarily locked after too many failed attempts...')
  return
}
if (result === 'blocked') {
  setError('Authentication blocked by security policy...')
  return
}
if (result === 'invalid') {
  setError('Invalid credentials...')
  return
}
```

What to say:

> We intentionally distinguish different failure states so the interface can guide the user appropriately while still respecting backend security decisions.

Likely question:

- Why not show the exact backend reason for every failure?
Answer: because some details help the user, while some details should remain generalized to avoid helping attackers.

---

### Segment 10: Dashboard as an Operational Overview

File:
`secure-bank-frontend/src/pages/dashboard/DashboardPage.tsx`

#### Code block: pulling data into the dashboard

```tsx
useEffect(() => {
  http.get<TransactionListResponse>('/transactions/?page=1&page_size=5')
    .then(r => setTransactions(r.data.transactions ?? r.data.items ?? []))
    .catch(() => setTransactions([]))
    .finally(() => setTxnLoading(false))
}, [])

useEffect(() => {
  http.get<FraudAlertListResponse>('/fraud/alerts/?status=open')
    .then(r => setOpenAlerts(r.data.total ?? 0))
    .catch(() => setOpenAlerts(0))
    .finally(() => setAlertsLoading(false))
}, [])
```

What this does:

- Fetches recent transactions.
- Fetches open fraud alert counts.

What to say:

> The dashboard is not static decoration. It is a live operational summary driven by backend state.

#### Code block: role-based UI on dashboard

```tsx
{hasRole('analyst') && !alertsLoading && openAlerts > 0 && (
  <div className="bg-red-50 ...">
    ...
    <Link to="/analyst/fraud">Review →</Link>
  </div>
)}
```

What to say:

> The same application adapts to the user's role. Regular users see personal finance functions, while analysts also see operational risk information relevant to fraud review.

This is a strong full-stack story because it mirrors backend role separation.

---

### Segment 11: Transaction Creation Page

File:
`secure-bank-frontend/src/pages/transactions/NewTransactionPage.tsx`

#### Code block: lightweight client-side risk estimate

```tsx
function estimateRisk(amount: string): { level: 'LOW' | 'MEDIUM' | 'HIGH'; colour: string; dot: string } {
  const n = parseFloat(amount) || 0
  if (n >= 10000) return { level: 'HIGH', colour: 'text-red-600', dot: 'bg-red-500' }
  if (n >= 1000)  return { level: 'MEDIUM', colour: 'text-amber-600', dot: 'bg-amber-500' }
  return { level: 'LOW', colour: 'text-emerald-600', dot: 'bg-emerald-500' }
}
```

What this does:

- Gives the user immediate visual feedback based on amount.
- Does not replace backend fraud scoring.

What to say:

> This is an interface hint, not a security decision. The real fraud decision remains on the backend. The frontend estimate exists to improve transparency and user understanding before submission.

Likely question:

- Why compute a risk estimate here if the backend already does it?
Answer: for user feedback and explainability, not for authority.

#### Code block: submit and interpret results

```tsx
const response = await http.post<TransactionResponse>(
  '/transactions/',
  payload,
  { validateStatus: s => s < 500 }
)

if (response.status === 403) {
  ...
  setResult({
    state: 'blocked',
    message: 'This transaction was blocked by our security systems...',
  })
  return
}

const txn = response.data as TransactionResponse

if (txn.status === 'flagged') {
  setResult({ state: 'flagged', txn })
  return
}

setResult({ state: 'success', txn })
```

What to say:

> This page treats transaction submission as a workflow with multiple safe outcomes: success, flagged for review, blocked by policy, or validation error.

Strong sentence:

> The UI does not assume every transaction succeeds. It reflects the real control flow of a secure banking system.

---

### Segment 12: Analyst Fraud Workspace

File:
`secure-bank-frontend/src/pages/analyst/FraudWorkspacePage.tsx`

This is one of the strongest frontend pages to defend because it proves the system supports operations, not just customers.

#### Code block: alert loading

```tsx
const fetchAlerts = useCallback(() => {
  setLoading(true)
  http.get<FraudAlertListResponse>('/fraud/alerts/?page=1&page_size=50')
    .then(r => {
      const all = r.data.alerts ?? r.data.items ?? []
      setAlerts(all)
      setTotal(r.data.total)
    })
    .catch(() => setAlerts([]))
    .finally(() => setLoading(false))
}, [])
```

What to say:

> This page is the operational face of the fraud subsystem. It loads open cases for analysts to triage and act upon.

#### Code block: analyst action

```tsx
await http.patch(`/fraud/alerts/${alertId}/status`, {
  status,
  resolution_notes: notes,
}, { validateStatus: s => s < 500 })
```

What to say:

> The analyst workspace turns backend fraud alerts into an investigation workflow. Analysts can claim cases, resolve them, or mark false positives, and those actions are synchronized back to the backend.

#### Code block: direct transaction control from case view

```tsx
await http.post(`/transactions/${txnId}/block`, {
  reason: 'Blocked via SEC_PROTOCOL from Fraud Workspace',
}, { validateStatus: s => s < 500 })
```

What to say:

> This is where operational intervention happens. The analyst is not only viewing data but executing controlled actions on risky transactions.

How to phrase it strongly:

> The frontend supports human-in-the-loop fraud response.

---

### Segment 13: Admin Control Center

File:
`secure-bank-frontend/src/pages/admin/AdminControlCenterPage.tsx`

This page shows administrative governance on the frontend.

#### Code block: user list loading

```tsx
const fetchUsers = useCallback(() => {
  setLoading(true)
  const params = new URLSearchParams({ page: '1', page_size: '20' })
  if (roleFilter) params.append('role', roleFilter)
  if (statusFilter) params.append('account_status', statusFilter)
  if (search) params.append('search', search)

  http.get<UserListResponse>(`/admin/users/?${params}`)
    .then(r => {
      setUsers(r.data.users ?? r.data.items ?? [])
      setTotal(r.data.total)
    })
    .catch(() => setUsers([]))
    .finally(() => setLoading(false))
}, [roleFilter, statusFilter, search])
```

What to say:

> The admin page surfaces user management as a searchable, filterable operational workflow. It is designed for governance tasks rather than normal consumer banking tasks.

#### Code block: status/role/session actions

```tsx
if (pending.type === 'status') {
  await http.patch(`/admin/users/${pending.userId}/status`, { status: actionVal }, ...)
} else if (pending.type === 'role') {
  await http.patch(`/admin/users/${pending.userId}/role`, { role: actionVal }, ...)
} else if (pending.type === 'sessions') {
  await http.delete(`/admin/users/${pending.userId}/sessions`, ...)
}
```

What to say:

> The admin console maps directly to backend governance endpoints. Each action corresponds to a controlled administrative capability: changing status, changing role, or invalidating active sessions.

#### Code block: system policy panel

```tsx
const [systemSettings, setSystemSettings] = useState<SystemPolicySettingsResponse>({
  daily_withdrawal_limit: 10_000_000,
  global_rate_limit: 50_000,
  multi_sig_internal_ops: true,
  forced_24h_password_cycle: false,
  updated_at: null,
})
```

What to say:

> This section demonstrates that the frontend is not just consuming business data. It also presents operational policy controls for administrators in a structured way.

Good honest note to say:

> In the current implementation, these settings support the demo admin workflow. In a production system they would be backed by a durable configuration service or database table.

---

### Segment 14: Frontend Teaching Order

Use this order when presenting the frontend:

1. `src/main.tsx`
2. `src/App.tsx`
3. `src/contexts/AuthContext.tsx`
4. `src/lib/token.ts`
5. `src/lib/http.ts`
6. `src/lib/fingerprint.ts`
7. `src/components/guards/RequireAuth.tsx`
8. `src/components/layout/AppShell.tsx`
9. `src/pages/auth/LoginPage.tsx`
10. `src/pages/auth/MfaSetupPage.tsx`
11. `src/pages/auth/MfaVerifyPage.tsx`
12. `src/pages/dashboard/DashboardPage.tsx`
13. `src/pages/transactions/NewTransactionPage.tsx`
14. `src/pages/transactions/TransactionsPage.tsx`
15. `src/pages/transactions/TransactionDetailPage.tsx`
16. `src/pages/analyst/FraudWorkspacePage.tsx`
17. `src/pages/admin/AdminControlCenterPage.tsx`

Why this order works:

- It starts from the browser boot process.
- Then it explains route structure.
- Then it explains authentication state.
- Then it explains API communication.
- Then it explains guarded UX.
- Then it shows business pages and role-specific operational pages.

---

### Segment 15: Strong Frontend "What To Say" Lines

Use these when you need short, confident answers.

#### On routing

> The route tree reflects the trust model of the application.

#### On auth context

> AuthContext is the single source of truth for session state on the frontend.

#### On refresh handling

> Token refresh is centralized so session recovery is consistent across the app.

#### On route guards

> Route guards improve UX by preventing unauthorized screens from rendering in the first place.

#### On token storage

> We chose in-memory token storage to reduce the attack surface for token theft.

#### On device fingerprinting

> The frontend supplies stable device context so the backend can distinguish familiar behavior from anomalies.

#### On role-based UI

> The interface adapts to role, but the backend remains the final authority.

#### On operational pages

> The analyst and admin pages show that this is not just a consumer app; it is also an operational platform.

---

### Segment 16: Best Spoken Frontend Walkthrough

Use this as your oral flow:

> The frontend starts in `main.tsx`, where React is mounted into the browser.  
> Then `App.tsx` composes the whole client application with routing and authentication context.  
> `AuthContext.tsx` manages session state, login outcomes, MFA pending state, logout, and role checks.  
> `http.ts` centralizes all API communication, automatically attaching tokens and device fingerprints and handling silent token refresh.  
> `RequireAuth.tsx` protects routes at the interface level, while `AppShell.tsx` gives authenticated users a consistent role-aware layout.  
> Then the business pages sit on top of that foundation: login and MFA pages for access control, dashboard and transactions for normal banking activity, fraud workspace for analysts, and the control center for administrators.

This is a strong frontend defense sequence.

---

### Segment 17: Full-Stack Bridge Statement

When moving from frontend to backend or vice versa, use this sentence:

> The frontend expresses the workflow and the backend enforces the workflow.

That line is extremely useful in a defense because it connects both sides cleanly.

Another excellent bridge line:

> The frontend is responsible for clarity, guidance, and controlled navigation; the backend is responsible for trust, validation, and final authorization.
