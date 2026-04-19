# Secure Banking Presentation Diagram Pack

Use this file as a single copy source for your presentation diagrams.

---

## 1) Use Case Diagram (PlantUML)

```plantuml
@startuml
left to right direction
skinparam packageStyle rectangle

actor "Customer" as Customer
actor "Analyst" as Analyst
actor "Admin" as Admin
actor "Fraud Engine" as Engine

rectangle "Secure Banking Platform" {
  usecase "Register Account" as UC_Register
  usecase "Login" as UC_Login
  usecase "Setup MFA" as UC_SetupMFA
  usecase "Verify MFA" as UC_VerifyMFA
  usecase "Create Transaction" as UC_CreateTxn
  usecase "View Transaction History" as UC_ViewTxn
  usecase "Detect Fraud Risk" as UC_DetectFraud
  usecase "View Fraud Alerts" as UC_ViewAlerts
  usecase "Investigate Alert" as UC_Investigate
  usecase "Block / Clear Transaction" as UC_ManageTxn
  usecase "Manage Users (Role/Status)" as UC_ManageUsers
  usecase "Force Logout Sessions" as UC_ForceLogout
  usecase "View Audit Logs" as UC_AuditLogs
  usecase "Apply System Policy Updates" as UC_Policy
}

Customer --> UC_Register
Customer --> UC_Login
Customer --> UC_SetupMFA
Customer --> UC_VerifyMFA
Customer --> UC_CreateTxn
Customer --> UC_ViewTxn

Analyst --> UC_ViewAlerts
Analyst --> UC_Investigate
Analyst --> UC_ManageTxn
Analyst --> UC_AuditLogs

Admin --> UC_ViewAlerts
Admin --> UC_Investigate
Admin --> UC_ManageTxn
Admin --> UC_ManageUsers
Admin --> UC_ForceLogout
Admin --> UC_AuditLogs
Admin --> UC_Policy

Engine --> UC_DetectFraud
UC_CreateTxn .> UC_DetectFraud : <<include>>
UC_Login .> UC_VerifyMFA : <<extend>>
@enduml
```

---

## 2) Login + MFA Sequence Diagram (Mermaid)

```mermaid
sequenceDiagram
autonumber
participant U as User
participant FE as Frontend
participant API as Auth API
participant AS as Auth Service
participant MFA as MFA Service
participant DB as Database
participant FR as Fraud Service

U->>FE: Enter email/username + password
FE->>API: POST /auth/login
API->>AS: login(credentials, context headers)
AS->>DB: validate user + password + account status
AS->>DB: check mfa_enabled
alt MFA enabled
  AS-->>API: MFARequired(mfa_pending_token)
  API-->>FE: 202 Accepted (mfa_required=true)
  U->>FE: Enter TOTP code
  FE->>API: POST /auth/mfa/verify (mfa_token, code)
  API->>AS: verify_mfa_and_login()
  AS->>MFA: verify_totp_or_backup()
  MFA->>DB: read/decrypt MFA secret, validate code
  AS->>FR: evaluate login risk
  FR-->>AS: allow/flag/block
  alt allow or flag
    AS->>DB: create session + login attempt
    AS-->>API: access + refresh tokens
    API-->>FE: 200 OK
  else block
    API-->>FE: 403/401 blocked by policy
  end
else MFA not enabled
  AS->>FR: evaluate login risk
  FR-->>AS: allow/flag/block
  AS-->>API: tokens or block
  API-->>FE: 200 or error
end
```

---

## 3) ER/Data Model Diagram (Mermaid)

```mermaid
erDiagram
  USERS ||--o{ SESSIONS : has
  USERS ||--o{ MFA_SECRETS : has
  USERS ||--o{ LOGIN_ATTEMPTS : records
  USERS ||--o{ TRANSACTIONS : creates
  USERS ||--o{ FRAUD_ALERTS : triggers
  USERS ||--o{ AUDIT_LOGS : performs
  USERS ||--o{ KNOWN_DEVICES : registers
  USERS ||--|| USER_BEHAVIOR_PATTERNS : has

  TRANSACTIONS ||--o{ FRAUD_ALERTS : linked_to

  USERS {
    uuid id PK
    string email
    string username
    string password_hash
    string role
    string account_status
    boolean mfa_enabled
    datetime created_at
  }

  SESSIONS {
    uuid id PK
    uuid user_id FK
    string access_token_hash
    string refresh_token_hash
    string device_fingerprint
    string ip_address
    string location_country
    string location_city
    boolean is_active
    datetime expires_at
  }

  MFA_SECRETS {
    uuid id PK
    uuid user_id FK
    string mfa_type
    bytes secret_encrypted
    bytes backup_codes_encrypted
    boolean is_active
  }

  TRANSACTIONS {
    uuid id PK
    uuid user_id FK
    string transaction_type
    decimal amount
    string status
    int risk_score
    string fraud_check_status
    string device_fingerprint
    string location_country
    string location_city
    datetime created_at
  }

  FRAUD_ALERTS {
    uuid id PK
    uuid user_id FK
    uuid transaction_id FK
    string alert_type
    string severity
    int risk_score
    json triggered_rules
    string status
    datetime created_at
  }

  AUDIT_LOGS {
    uuid id PK
    uuid user_id FK
    string action
    string entity_type
    uuid entity_id
    json old_values
    json new_values
    string ip_address
    boolean success
    datetime created_at
  }
```

---

## 4) Transaction Lifecycle State Model (Mermaid)

```mermaid
stateDiagram-v2
  [*] --> Pending

  Pending --> Blocked: risk >= block threshold
  Pending --> Flagged: risk >= flag threshold
  Pending --> Processing: process request (authorized)

  Flagged --> Pending: analyst/admin clear
  Flagged --> Blocked: analyst/admin block

  Processing --> Completed: processing success
  Processing --> Failed: processing error

  Blocked --> [*]
  Failed --> [*]
  Completed --> [*]
```

---

## 5) Communication/Protocol Diagram (Mermaid)

```mermaid
flowchart LR
  FE[Frontend SPA] -- HTTPS + JWT --> API[FastAPI Backend]
  API -- SQLAlchemy --> DB[(PostgreSQL)]
  API -- Rule Evaluation Calls --> FRAUD[Fraud Service]
  API -- TOTP Verify + Secret Decrypt --> MFA[MFA Module]
  API -- Audit Write --> AUDIT[(Audit Logs)]

  FE -- Headers --> API
  H1[X-Device-Fingerprint]
  H2[X-Location-Country]
  H3[X-Location-City]
  H1 --> API
  H2 --> API
  H3 --> API
```

---

## 6) Prompt for Eraser / Replit AI Diagram Tools

```text
Generate professional UML diagrams for a secure online banking prototype with roles user, analyst, admin.

Include:
1. Use case diagram for registration, login, MFA setup/verify, transaction creation, fraud alert investigation, admin user/status/role/session management, audit log access.
2. Sequence diagram for login with MFA pending token and TOTP verification.
3. ER diagram with tables: users, sessions, mfa_secrets, login_attempts, transactions, fraud_alerts, audit_logs, known_devices, user_behavior_patterns.
4. State machine (Petri-net style) for transaction lifecycle: pending -> flagged/blocked/processing -> completed/failed.
5. Communication model showing frontend HTTPS calls, device/location headers, backend service layers, fraud engine, and database.

Add security notes:
- JWT scope-based access control
- rate limiting on auth endpoints
- audit trail for privileged actions
- analyst/admin workflow for flagged transactions

Use clear labels, actor boundaries, and banking-grade visual style suitable for academic presentation.
```

---

## 7) Quick Tool Notes

- PlantUML block works in: PlantUML renderers, VSCode PlantUML plugin, online PlantUML servers.
- Mermaid blocks work in: Mermaid Live Editor, Eraser markdown, many markdown-enabled tools, Replit docs.
- If a tool supports one format only:
  - Use PlantUML for use case
  - Use Mermaid for sequence, ER, state, and flow

