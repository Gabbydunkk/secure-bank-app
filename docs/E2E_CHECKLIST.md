# E2E Smoke Checklist

## Prerequisites
- Backend running at `http://127.0.0.1:8000`
- Frontend running at `http://localhost:5173`
- DB migrated (`alembic upgrade head`)

## 1) User Journey
1. Register user.
2. Login.
3. Complete MFA setup and confirm.
4. Logout.
5. Login again and complete MFA verify.
6. Create low-risk transaction and process it.

Expected:
- Login/MFA flows succeed.
- Transaction appears in history.

## 2) Fraud Journey
1. Create high-risk transaction to trigger flagged/blocked behavior.
2. Verify alert appears in `/fraud/alerts` for that user.

Expected:
- Status + risk score consistent.
- Alert row created.

## 3) Analyst/Admin Security Boundary
1. Login as analyst or admin.
2. Open fraud workspace.
3. Attempt alert status update.
4. Attempt transaction block/clear by transaction ID.

Expected:
- Alert update allowed.
- Block/clear allowed.
- NOTE: global transaction review list is currently missing from API.

## 4) Final Regression Command
Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sanity_check.ps1
```

Expected:
- Backend tests pass
- Frontend build passes
