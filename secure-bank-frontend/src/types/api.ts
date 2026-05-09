// src/types/api.ts
// Generated to match backend Pydantic schemas exactly.
// If the backend schema changes, update this file to match.

// ── Enums (mirror backend Literal types) ─────────────────────────────────

export type UserRole = 'user' | 'analyst' | 'admin'
export type AccountStatus = 'active' | 'suspended' | 'locked' | 'closed'
export type TransactionType = 'transfer' | 'payment' | 'withdrawal' | 'deposit'
export type TransactionStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'flagged'
export type FraudCheckStatus = 'pending' | 'approved' | 'flagged' | 'blocked'
export type AlertType =
  | 'suspicious_login'
  | 'unusual_transaction'
  | 'velocity_breach'
  | 'location_anomaly'
  | 'device_change'
  | 'pattern_anomaly'
export type FraudSeverity = 'low' | 'medium' | 'high' | 'critical'
export type FraudAlertStatus = 'open' | 'investigating' | 'resolved' | 'false_positive'

// ── Auth ─────────────────────────────────────────────────────────────────

export interface Token {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number // seconds
}

/** Returned by POST /auth/login on success (200) */
export interface LoginResponse {
  tokens: Token | null       // null when mfa_required=true
  mfa_token: string | null   // set when mfa_required=true (202)
  user_id: string
  email: string
  username: string
  mfa_required: boolean
  mfa_setup_required: boolean
  risk_flagged: boolean      // true = fraud engine flagged but allowed — show warning
}

/** Body of the 202 response when MFA verification is needed */
export interface MFAPendingResponse {
  mfa_required: true
  mfa_token: string          // submit this to POST /auth/mfa/verify
  user_id: string
  email: string
  message: string
}

/** Returned by POST /auth/mfa/setup */
export interface MFASetupResponse {
  secret: string             // base32 — show ONCE, cannot be retrieved again
  provisioning_uri: string   // encode as QR code client-side
  backup_codes: string[]     // 8 single-use codes — show ONCE
  message: string
}

export interface RefreshTokenRequest {
  refresh_token: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string       // min 12 chars, upper, lower, digit, special
}

// ── Users ────────────────────────────────────────────────────────────────

export interface UserResponse {
  id: string
  email: string
  username: string
  first_name: string
  last_name: string
  phone_number: string | null
  date_of_birth: string | null  // ISO date string
  role: UserRole
  account_status: AccountStatus
  mfa_enabled: boolean
  created_at: string            // ISO datetime string
}

export interface UserProfileUpdate {
  first_name?: string
  last_name?: string
  phone_number?: string
  date_of_birth?: string
}

export interface KnownDeviceResponse {
  id: string
  device_fingerprint: string
  device_name: string | null
  device_type: string | null
  first_seen: string | null
  last_seen: string | null
  is_trusted: boolean
  trust_expires_at: string | null
}

export interface KnownDeviceListResponse {
  items: KnownDeviceResponse[]
  devices: KnownDeviceResponse[]  // legacy alias — same data
  total: number
}

export interface UserBalanceSummary {
  opening_balance: number
  current_balance: number
  total_inflows: number
  total_outflows: number
  pending_outflows: number
  pending_inflows: number
}

// ── Transactions ─────────────────────────────────────────────────────────

export interface TransactionCreate {
  transaction_type: TransactionType
  amount: string              // send as string to preserve decimal precision
  currency?: string           // defaults to "USD"
  recipient_account?: string
  recipient_name?: string
  description?: string
}

export interface TransactionResponse {
  id: string
  user_id: string
  transaction_type: TransactionType
  amount: string              // Decimal returned as string from FastAPI
  currency: string
  recipient_account: string | null
  recipient_name: string | null
  description: string | null
  status: TransactionStatus
  risk_score: number | null   // 0-100
  fraud_check_status: FraudCheckStatus
  ip_address: string | null
  device_fingerprint: string | null
  location_country: string | null
  location_city: string | null
  created_at: string
  processed_at: string | null
  completed_at: string | null
}

export interface TransactionListResponse {
  items: TransactionResponse[]
  transactions: TransactionResponse[]  // legacy alias — same data
  total: number
}

// ── Fraud alerts ─────────────────────────────────────────────────────────

export interface FraudAlertResponse {
  id: string
  user_id: string | null
  transaction_id: string | null
  session_id: string | null
  alert_type: AlertType
  severity: FraudSeverity
  risk_score: number | null
  description: string | null
  triggered_rules: Record<string, number> | null
  status: FraudAlertStatus
  assigned_to: string | null
  resolution_notes: string | null
  created_at: string
  resolved_at: string | null
}

export interface FraudAlertListResponse {
  items: FraudAlertResponse[]
  alerts: FraudAlertResponse[]  // legacy alias — same data
  total: number
}

export interface AlertStatusUpdate {
  status: FraudAlertStatus
  resolution_notes?: string   // required when status is resolved or false_positive
  assigned_to?: string
}

// ── Audit logs ───────────────────────────────────────────────────────────

export interface AuditLogResponse {
  id: string
  user_id: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  success: boolean
  error_message: string | null
  created_at: string
}

export interface AuditLogListResponse {
  items: AuditLogResponse[]
  logs: AuditLogResponse[]  // legacy alias — same data
  total: number
}

// ── Admin ────────────────────────────────────────────────────────────────

export interface UserListResponse {
  items: UserResponse[]
  users: UserResponse[]  // legacy alias — same data
  total: number
}

export interface StatusUpdateBody {
  status: AccountStatus
  reason?: string
}

export interface RoleUpdateBody {
  role: UserRole
}

export interface SessionInvalidationResponse {
  sessions_invalidated: number
  message: string
}

export interface SystemPolicySettingsResponse {
  daily_withdrawal_limit: number
  global_rate_limit: number
  multi_sig_internal_ops: boolean
  forced_24h_password_cycle: boolean
  updated_at: string | null
}

export interface SystemPolicySettingsUpdateBody {
  daily_withdrawal_limit?: number
  global_rate_limit?: number
  multi_sig_internal_ops?: boolean
  forced_24h_password_cycle?: boolean
}

// ── Shared ───────────────────────────────────────────────────────────────

/** FastAPI validation error shape */
export interface ApiValidationError {
  detail: Array<{
    loc: (string | number)[]
    msg: string
    type: string
  }>
}

/** FastAPI HTTP error shape */
export interface ApiError {
  detail: string
}

export interface PaginationParams {
  page?: number
  page_size?: number
}
