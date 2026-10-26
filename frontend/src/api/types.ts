// Shapes mirror hunt/api/serializers.py and hunt/api/app.py. Anything the backend
// may omit or null is typed as optional/nullable so the UI degrades gracefully.

export type JobStatus =
  | 'discovered'
  | 'eligibility_review'
  | 'matched'
  | 'resume_generated'
  | 'ready_to_apply'
  | 'applying'
  | 'submitted'
  | 'assessment'
  | 'interview'
  | 'offer'
  | 'rejected'
  | 'withdrawn'
  | 'blocked'
  | 'failed'
  | 'expired'
  | 'ineligible'
  | 'skipped'

export type Eligibility = 'unknown' | 'eligible' | 'review' | 'ineligible'

export interface JobSummary {
  id: number
  uid: string
  company: string
  title: string
  location: string | null
  locations: string[]
  remote_type: string | null
  category: string | null
  match_score: number | null
  match_tier: string | null
  priority: number | null
  eligibility: Eligibility | string
  eligibility_category: string | null
  status: JobStatus
  next_action: string | null
  date_posted: string | null
  date_discovered: string | null
  status_updated_at: string | null
  salary_text: string | null
  salary_min: number | null
  salary_max: number | null
  salary_period: string | null
  source: string
  sources: string[]
  ats_platform: string | null
  apply_url: string | null
  posting_url: string | null
  has_resume: boolean
  resume_version: string | null
  has_cover_letter: boolean
  lesser_known: boolean
  verified_active: boolean | null
  terms: string[]
  term_status: string | null
  apply_method: string | null
  approved: boolean
  date_applied: string | null
  is_test: boolean
  open_questions: number
}

export interface ScoreComponent {
  score: number
  weight: number
  points: number
}

export interface EvidenceItem {
  entry: string
  bullet_id: string
  text: string
  skills: string[]
  relevance: number
}

export interface ScoreExplanation {
  summary?: string
  strengths?: string[]
  gaps?: string[]
  evidence?: EvidenceItem[]
  required_skills?: string[]
  preferred_skills?: string[]
  matched_skills?: string[]
  missing_required?: string[]
  missing_preferred?: string[]
  location_tier?: string
  timing?: string
  gates?: string[]
  requirements_sectioned?: boolean
  required_lines?: string[]
  preferred_lines?: string[]
}

export interface EligibilityReason {
  category: string
  verdict: string
  rule: string
  quote: string
}

export interface ResumeChange {
  type: string
  entry?: string
  bullet?: string
  detail?: string
  before?: string
  after?: string
}

export interface FactCheck {
  passed?: boolean
  violations_reverted?: string[]
  rejected_rewrites?: { bullet: string; proposed: string; issues: string[] | string }[]
  rules?: string[]
}

export interface AtsCheck {
  passed?: boolean
  checks?: { name: string; passed: boolean; detail?: string }[]
  keyword_coverage?: { present: string[]; absent: string[]; ratio: number } | null
}

export interface ResumeVersion {
  id: number
  version_id: string
  created_at: string | null
  master_version: number
  keywords: string[]
  matched_keywords: string[]
  changes: ResumeChange[]
  factcheck: FactCheck
  ats_check: AtsCheck
  match_score: number | null
  llm_used: boolean
  download_url: string
}

export interface PlannedAnswer {
  name: string
  label: string
  type: string
  required: boolean
  value: string | string[] | null
  kind: 'fixed' | 'contextual' | 'sensitive' | 'file' | 'human' | 'skip' | string
  rule?: string | null
  reason?: string | null
  options?: string[]
  option_values?: string[]
}

export interface ApplicationPlan {
  platform?: string
  form_url?: string | null
  form_source?: string
  answers?: PlannedAnswer[]
  live_answers?: PlannedAnswer[]
  notes?: string[]
  prepared_at?: string
  manual_reason?: string | null
}

export interface UnresolvedQuestion {
  question: string
  reason: string | null
  field: string | null
  id: number
}

export interface Application {
  id: number
  apply_method: string
  platform: string | null
  approved: boolean
  approved_at: string | null
  attempts: number
  last_attempt_at: string | null
  date_applied: string | null
  confirmation_text: string | null
  confirmation_source: string | null
  last_error: string | null
  plan: ApplicationPlan | null
  unresolved: UnresolvedQuestion[] | null
  contradictions: string[] | null
  evidence_url: string | null
  cover_letter_url: string | null
}

export interface StatusEventRow {
  from: string | null
  to: string
  reason: string | null
  actor: string
  at: string | null
  run_id: number | null
}

export interface Question {
  id: number
  job_id: number
  question: string
  field_name: string | null
  field_type: string | null
  options: string[] | null
  required: boolean
  reason: string | null
  answer: string | null
  status: 'open' | 'answered' | 'dismissed' | string
  created_at: string | null
  company: string | null
  title: string | null
}

export interface JobDetail extends JobSummary {
  description_text: string | null
  required_quals: string[] | null
  preferred_quals: string[] | null
  deadline: string | null
  internship_dates: string | null
  degrees: string[] | null
  ats_board: string | null
  ats_job_id: string | null
  canonical_key: string
  verified_at: string | null
  verification_note: string | null
  feed_flags: Record<string, unknown> | null
  eligibility_reasons: EligibilityReason[] | null
  work_auth_text: string[] | null
  score_breakdown: Record<string, ScoreComponent>
  score_explanation: ScoreExplanation | null
  notes: string | null
  last_error: string | null
  resume_versions: ResumeVersion[]
  application: Application | null
  events: StatusEventRow[]
  questions: Question[]
  emails: { subject: string; sender: string; category: string; received_at: string | null }[]
}

export interface JobsResponse {
  items: JobSummary[]
  total: number
  page: number
  page_size: number
  facets: {
    categories: Record<string, number>
    statuses: Record<string, number>
    eligibility: Record<string, number>
  }
}

export interface RunSummary {
  id: number
  trigger: string
  status: 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled' | string
  dry_run: boolean
  current_stage: string | null
  started_at: string | null
  finished_at: string | null
  stats: Record<string, unknown> | null
  error: string | null
  cancel_requested: boolean
  report_url: string | null
}

export interface StageRow {
  stage: string
  status: string
  started_at: string | null
  finished_at: string | null
  processed: number
  error: string | null
  result: Record<string, unknown> | null
}

export interface RunDetail extends RunSummary {
  stages: StageRow[]
}

export interface RunLogRow {
  id: number
  level: string
  stage: string | null
  job_id: number | null
  message: string
  at: string | null
}

export interface TaskRow {
  id: number
  kind: string
  status: string
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  last_error: string | null
  payload: Record<string, unknown> | null
}

export interface StatusResponse {
  scheduler_running: boolean
  schedule: string
  next_run: string | null
  last_run: RunSummary | null
  active_run: RunSummary | null
  automation_enabled: boolean
  paused: boolean
  apply_mode: 'auto' | 'review' | string
  llm_available: boolean
  llm_model: string
  imap_configured: boolean
  smtp_configured: boolean
  encryption_enabled: boolean
  allow_real_submissions: boolean
  playwright_available: boolean
  onboarding_blockers: string[]
  warnings: string[]
  database: string
  submitted_today?: number
  daily_submission_target?: number | null
  finish_queue?: number
}

export interface DailyTriple {
  discovered: number
  resumes: number
  submitted: number
}

export interface OverviewResponse {
  total_discovered: number
  eligible: number
  eligibility_review: number
  ineligible: number
  high_match: number
  resumes_generated: number
  applications_submitted: number
  awaiting_review: number
  blocked: number
  failed: number
  interviews: number
  offers: number
  response_rate: number | null
  open_questions: number
  status_counts: Record<string, number>
  tier_counts: Record<string, number>
  series: { days: string[]; discovered: number[]; resumes: number[]; submitted: number[] }
  week: DailyTriple
  today: DailyTriple
  top_opportunities: JobSummary[]
}

export type PipelineResponse = Record<JobStatus, { total: number; items: JobSummary[] }>

export interface NotificationRow {
  id: number
  kind: string
  title: string
  body: string | null
  job_id: number | null
  read: boolean
  created_at: string | null
}

export interface AnswerRow {
  key: string
  label: string
  answer: string | null
  kind: string
  sensitive: boolean
  approved: boolean
  source: string
  patterns: string[]
  updated_at: string | null
}

export interface BoardRow {
  id: number
  platform: string
  token: string
  company: string | null
  metro: string | null
  industry: string | null
  origin: 'seed' | 'learned' | 'user' | string
  active: boolean
  last_polled_at: string | null
  last_error: string | null
  jobs_found: number
}

export interface OnboardingItem {
  path: string
  label: string
  required: boolean
  help: string
  value: unknown
  complete: boolean
}

export type Profile = Record<string, unknown>

export interface ProfileResponse {
  profile: Profile
  onboarding: OnboardingItem[]
  auto_apply_blockers: string[]
}

export interface MasterResumeEntryBullet {
  id: string
  text: string
}

export interface MasterResume {
  basics?: Record<string, string>
  education?: Record<string, string>[]
  experience?: { id: string; org: string; title: string; dates: string; location?: string; tech?: string[]; bullets: MasterResumeEntryBullet[] }[]
  projects?: { id: string; name: string; context?: string; tech?: string[]; bullets: MasterResumeEntryBullet[] }[]
  skills?: { category: string; items: string[] }[]
  [k: string]: unknown
}

export interface AutomationSettings {
  automation_enabled: boolean
  paused: boolean
  apply_mode: 'auto' | 'review'
  preferred_cities: string[]
  include_nearby_metros: boolean
  include_remote_us: boolean
  include_other_us: boolean
  target_roles: string[]
  daily_discovery_target: number
  daily_resume_cap: number
  daily_application_cap: number
  daily_submission_target: number
  apply_loop_max_minutes: number
  assisted_only_platforms: string[]
  min_match_score: number
  min_auto_apply_score: number
  max_posting_age_days: number
  scoring_weights: Record<string, number>
  lesser_known_boost: number
  resume: {
    use_llm: boolean
    one_page: boolean
    max_projects: number
    reword_bullets: boolean
    cover_letters: 'when_required' | 'always' | 'never' | string
  }
  eligibility: Record<string, string>
  auto_contextual_answers: boolean
  blacklist: string[]
  whitelist: string[]
  sources: Record<string, boolean>
  learn_boards_from_feeds: boolean
  max_learned_boards_per_run: number
  [k: string]: unknown
}

export type AssistState = 'idle' | 'starting' | 'filling' | 'waiting' | 'confirmed' | 'closed' | 'timeout' | 'cancelled' | 'error' | 'done'

/** Finish all: progress through the queue of applications waiting for you. */
export interface AssistQueue {
  total: number
  position: number
  submitted: number
  skipped: number
}

/** GET /api/assist — the visible-browser "Finish application" session. */
export interface AssistStatus {
  job_id: number | null
  company: string | null
  title: string | null
  state: AssistState
  message: string
  started_at: string | null
  finished_at: string | null
  filled: number
  left_for_you: string[]
  queue: AssistQueue | null
  /** emailed verification code found in your inbox, for you to type in */
  code: string | null
}
