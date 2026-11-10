export type Decision = 'allow' | 'review' | 'block'
export type ReviewStatus = 'pending' | 'cleared' | 'confirmed'

export interface Me {
  id: number
  username: string
  email: string
  role: string
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface RuleHit {
  reason_code: string
  detail: string
  points: number
  shadow: boolean
}

export interface BookingSummary {
  id: number
  owner: string
  sitter: string
  start_date: string
  end_date: string
  amount: string
  currency: string
  status: string
}

export interface Assessment {
  id: number
  user: string
  user_id: number
  booking: BookingSummary
  score: number
  decision: Decision
  review_status: ReviewStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string
  created_at: string
  hits: RuleHit[]
}

export interface ConsoleUser {
  id: number
  username: string
  email: string
  role: string
  status: 'active' | 'suspended'
  country: string
  phone_number: string
  signup_ip: string | null
  date_joined: string
  max_score: number | null
  assessment_count: number
  sitter_max_score: number | null
  sitter_flagged_count: number
  risk_score: number
  verification_state: VerificationState | null
  recent_assessments?: Assessment[]
  received_assessments?: Assessment[]
}

export interface AuditEntry {
  id: number
  actor_label: string
  action: string
  target_type: string
  target_id: number
  metadata: Record<string, unknown>
  created_at: string
}

export type Verdict = 'clean' | 'flagged' | 'needs_review'

export interface Moderation {
  id: number
  message: { id: number; booking_id: number; sender: string; body: string; created_at: string }
  verdict: Verdict
  stage: 'rules' | 'llm' | 'llm_unavailable'
  categories: string[]
  reasons: string[]
  confidence: number | null
  llm_model: string
  llm_input_tokens: number | null
  llm_output_tokens: number | null
  llm_latency_ms: number | null
  review_status: ReviewStatus
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string
  created_at: string
}

export type VerificationState =
  | 'requested'
  | 'submitted'
  | 'manual_review'
  | 'verified'
  | 'rejected'

export interface VerificationEvent {
  from_state: string
  to_state: string
  source: 'user' | 'provider' | 'agent' | 'system'
  actor_label: string
  detail: string
  created_at: string
}

export interface VerificationCase {
  id: number
  user: string
  user_id: number
  state: VerificationState
  full_name: string
  document_number_masked: string
  document_country: string
  rejection_reason: string
  provider_ref: string | null
  submitted_at: string | null
  decided_at: string | null
  purged_at: string | null
  created_at: string
  events: VerificationEvent[]
}
