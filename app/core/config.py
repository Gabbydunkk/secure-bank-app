# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Secure Bank Pro"
    API_V1_STR: str = "/api/v1"
    model_config = SettingsConfigDict(env_file=".env")
    # Comma-separated list, e.g.:
    # BACKEND_CORS_ORIGINS=https://bank.example.com,https://staging.bank.example.com,http://localhost:3000
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    DATABASE_URL: str = "postgresql://postgres:fake_placeholder@localhost:5432/fake_db"
    SECRET_KEY: str = "fake_placeholder_secret_key_do_not_use"

    # JWT
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCK_MINUTES: int = 15

    # MFA
    # Short-lived: user has this many minutes to enter their TOTP code after password check.
    # 5 minutes is long enough to pick up a phone, short enough to limit replay risk.
    MFA_PENDING_EXPIRE_MINUTES: int = 5

    # Fraud – configurable without redeploy (env or .env)
    FRAUD_RESTRICTED_COUNTRIES: str = "XX,YY"
    FRAUD_VELOCITY_WINDOW_MINUTES: int = 10
    FRAUD_VELOCITY_THRESHOLD_ATTEMPTS: int = 5
    FRAUD_LARGE_AMOUNT_THRESHOLD: float = 10_000.0
    FRAUD_SCORE_BLOCK: int = 90
    FRAUD_SCORE_CHALLENGE: int = 70
    FRAUD_SCORE_FLAG: int = 40

    # DB connection: "require" = SSL mandatory (prod). "prefer" for local dev.
    DATABASE_SSLMODE: str = "require"

    @property
    def fraud_restricted_countries_set(self) -> set[str]:
        return {c.strip().upper()[:2] for c in self.FRAUD_RESTRICTED_COUNTRIES.split(",") if c.strip()}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

# -----------------------------------------------------------------------------
# FEATURE TOGGLE: CLOUD-AWARENESS
# Set this to True for the DevOps Tutorial / AWS Deployment.
# Set this to False for the Security Course / Local Panel Defense.
# -----------------------------------------------------------------------------
ENABLE_CLOUD_FEATURES = True 

def apply_cloud_overrides():
    import os
    import logging

    # Guardrail 1: Check the Feature Toggle
    if not ENABLE_CLOUD_FEATURES:
        return

    # Guardrail 2: Ensure we are in the AWS 'Tutorial' environment
    if os.environ.get("APP_ENV") != "Tutorial":
        return

    # Lazy-loading boto3 so it doesn't break your local environment 
    # if boto3 isn't installed during your Security panel.
    try:
        import boto3
    except ImportError:
        logging.warning("Cloud features enabled but 'boto3' not found in environment.")
        return

    logger = logging.getLogger(__name__)
    try:
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        
        # Fetch the parameters defined in Terraform (rds.tf)
        response = ssm.get_parameters(
            Names=[
                "/bankapp/database/host",
                "/bankapp/database/username",
                "/bankapp/database/password",
                "/bankapp/database/name",
                "/bankapp/auth/jwt_secret"
            ],
            WithDecryption=True,
        )
        
        # Convert AWS response into a usable dictionary
        kv = {p["Name"]: p["Value"] for p in response.get("Parameters",[])}
        
        # 1. Reconstruct the Database Connection String from AWS secrets
        if all(k in kv for k in["/bankapp/database/host", "/bankapp/database/username", "/bankapp/database/password"]):
            db_url = (
                f"postgresql://{kv['/bankapp/database/username']}:"
                f"{kv['/bankapp/database/password']}@"
                f"{kv['/bankapp/database/host']}:5432/"
                f"{kv['/bankapp/database/name']}?sslmode={settings.DATABASE_SSLMODE}"
            )
            # OVERWRITE the local Pydantic setting with the Cloud URL
            settings.DATABASE_URL = db_url
        # 2. Explicitly whitelist the AWS S3 Frontend for CORS
            settings.BACKEND_CORS_ORIGINS = "http://secure-banking-frontend-953175116311.s3-website-us-east-1.amazonaws.com"
        # 2. Inject the cryptographically generated JWT Secret from AWS
        if "/bankapp/auth/jwt_secret" in kv:
            settings.SECRET_KEY = kv["/bankapp/auth/jwt_secret"]
            
        logger.info("✅ SUCCESS: Synchronized configuration with AWS SSM Parameter Store.")

    except Exception as e:
        logger.error(f"⚠️ Cloud-Aware Sync Failed: {e}. Defaulting to local .env environment.")

# Execute the sync immediately after settings = Settings()
apply_cloud_overrides()