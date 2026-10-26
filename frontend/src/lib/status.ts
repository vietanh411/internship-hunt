// The one status color system used everywhere: badges, kanban columns, timelines.
import type { JobStatus } from '../api/types'

export type Tone =
  | 'slate'
  | 'gray'
  | 'zinc'
  | 'stone'
  | 'amber'
  | 'orange'
  | 'red'
  | 'rose'
  | 'sky'
  | 'blue'
  | 'indigo'
  | 'violet'
  | 'teal'
  | 'cyan'
  | 'emerald'
  | 'green'

// Literal class strings so Tailwind's JIT picks them up.
export const TONE_BADGE: Record<Tone, string> = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-500/20 dark:bg-slate-400/10 dark:text-slate-300 dark:ring-slate-400/25',
  gray: 'bg-gray-100 text-gray-600 ring-gray-500/20 dark:bg-gray-400/10 dark:text-gray-400 dark:ring-gray-400/20',
  zinc: 'bg-zinc-100 text-zinc-600 ring-zinc-500/20 dark:bg-zinc-400/10 dark:text-zinc-400 dark:ring-zinc-400/20',
  stone: 'bg-stone-100 text-stone-600 ring-stone-500/20 dark:bg-stone-400/10 dark:text-stone-400 dark:ring-stone-400/20',
  amber: 'bg-amber-50 text-amber-800 ring-amber-600/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25',
  orange: 'bg-orange-50 text-orange-800 ring-orange-600/25 dark:bg-orange-400/10 dark:text-orange-300 dark:ring-orange-400/25',
  red: 'bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-400/10 dark:text-red-300 dark:ring-red-400/25',
  rose: 'bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-400/10 dark:text-rose-300 dark:ring-rose-400/25',
  sky: 'bg-sky-50 text-sky-800 ring-sky-600/20 dark:bg-sky-400/10 dark:text-sky-300 dark:ring-sky-400/25',
  blue: 'bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-400/10 dark:text-blue-300 dark:ring-blue-400/25',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-600/20 dark:bg-indigo-400/10 dark:text-indigo-300 dark:ring-indigo-400/25',
  violet: 'bg-violet-50 text-violet-700 ring-violet-600/20 dark:bg-violet-400/10 dark:text-violet-300 dark:ring-violet-400/25',
  teal: 'bg-teal-50 text-teal-800 ring-teal-600/20 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-400/25',
  cyan: 'bg-cyan-50 text-cyan-800 ring-cyan-600/20 dark:bg-cyan-400/10 dark:text-cyan-300 dark:ring-cyan-400/25',
  emerald: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/25',
  green: 'bg-green-100 text-green-800 ring-green-600/25 dark:bg-green-400/15 dark:text-green-300 dark:ring-green-400/30',
}

export const TONE_DOT: Record<Tone, string> = {
  slate: 'bg-slate-400',
  gray: 'bg-gray-400',
  zinc: 'bg-zinc-400',
  stone: 'bg-stone-400',
  amber: 'bg-amber-500',
  orange: 'bg-orange-500',
  red: 'bg-red-500',
  rose: 'bg-rose-500',
  sky: 'bg-sky-500',
  blue: 'bg-blue-500',
  indigo: 'bg-indigo-500',
  violet: 'bg-violet-500',
  teal: 'bg-teal-500',
  cyan: 'bg-cyan-500',
  emerald: 'bg-emerald-500',
  green: 'bg-green-600',
}

/** Top border accent for kanban columns. */
export const TONE_BORDER: Record<Tone, string> = {
  slate: 'border-t-slate-400',
  gray: 'border-t-gray-400',
  zinc: 'border-t-zinc-400',
  stone: 'border-t-stone-400',
  amber: 'border-t-amber-500',
  orange: 'border-t-orange-500',
  red: 'border-t-red-500',
  rose: 'border-t-rose-500',
  sky: 'border-t-sky-500',
  blue: 'border-t-blue-500',
  indigo: 'border-t-indigo-500',
  violet: 'border-t-violet-500',
  teal: 'border-t-teal-500',
  cyan: 'border-t-cyan-500',
  emerald: 'border-t-emerald-500',
  green: 'border-t-green-600',
}

export const STATUS_META: Record<JobStatus, { label: string; tone: Tone; help: string }> = {
  discovered: { label: 'Discovered', tone: 'slate', help: 'Found by discovery; not yet screened.' },
  eligibility_review: { label: 'Eligibility Review', tone: 'amber', help: 'Work-authorization language needs your review.' },
  matched: { label: 'Matched', tone: 'sky', help: 'Eligible and scored; queued for resume tailoring.' },
  resume_generated: { label: 'Resume Generated', tone: 'indigo', help: 'Tailored resume ready; application being prepared.' },
  ready_to_apply: { label: 'Ready to Apply', tone: 'violet', help: 'Application prepared; awaiting approval or manual apply.' },
  applying: { label: 'Applying', tone: 'blue', help: 'Submission in progress.' },
  submitted: { label: 'Submitted', tone: 'teal', help: 'Application sent.' },
  assessment: { label: 'Assessment', tone: 'cyan', help: 'Online assessment requested.' },
  interview: { label: 'Interview', tone: 'emerald', help: 'Interview stage.' },
  offer: { label: 'Offer', tone: 'green', help: 'Offer received.' },
  rejected: { label: 'Rejected', tone: 'rose', help: 'Employer declined.' },
  withdrawn: { label: 'Withdrawn', tone: 'zinc', help: 'You withdrew.' },
  blocked: { label: 'Blocked', tone: 'orange', help: 'Needs your input before it can continue.' },
  failed: { label: 'Failed', tone: 'red', help: 'An automated step failed.' },
  expired: { label: 'Expired', tone: 'stone', help: 'Posting closed.' },
  ineligible: { label: 'Ineligible', tone: 'gray', help: 'Work-authorization requirements exclude you.' },
  skipped: { label: 'Skipped', tone: 'zinc', help: "You chose not to apply; it won't be offered again." },
}

export const WORKFLOW_ORDER: JobStatus[] = [
  'discovered',
  'eligibility_review',
  'matched',
  'resume_generated',
  'ready_to_apply',
  'applying',
  'submitted',
  'assessment',
  'interview',
  'offer',
  'rejected',
  'withdrawn',
]
export const EXCEPTION_ORDER: JobStatus[] = ['blocked', 'failed', 'expired', 'ineligible', 'skipped']
export const ALL_STATUSES: JobStatus[] = [...WORKFLOW_ORDER, ...EXCEPTION_ORDER]

/** Statuses the API accepts for manual changes (POST /api/jobs/{id}/status). */
export const MANUAL_STATUSES: JobStatus[] = [
  'matched',
  'ready_to_apply',
  'submitted',
  'assessment',
  'interview',
  'offer',
  'rejected',
  'withdrawn',
  'expired',
  'skipped',
]

export const POST_SUBMISSION: JobStatus[] = ['submitted', 'assessment', 'interview', 'offer', 'rejected', 'withdrawn']

export function statusMeta(s: string) {
  return STATUS_META[s as JobStatus] ?? { label: s, tone: 'slate' as Tone, help: '' }
}

export const ELIGIBILITY_META: Record<string, { label: string; tone: Tone }> = {
  eligible: { label: 'Eligible', tone: 'emerald' },
  review: { label: 'Needs review', tone: 'amber' },
  ineligible: { label: 'Ineligible', tone: 'red' },
  unknown: { label: 'Unknown', tone: 'slate' },
}

export function eligibilityMeta(e: string | null | undefined) {
  return ELIGIBILITY_META[e ?? 'unknown'] ?? { label: e ?? 'Unknown', tone: 'slate' as Tone }
}

export type Tier = 'excellent' | 'strong' | 'moderate' | 'low'

export function tierOf(score: number | null | undefined): Tier | null {
  if (score === null || score === undefined) return null
  if (score >= 85) return 'excellent'
  if (score >= 70) return 'strong'
  if (score >= 55) return 'moderate'
  return 'low'
}

export const TIER_META: Record<Tier, { label: string; tone: Tone; solid: string }> = {
  excellent: { label: 'Excellent', tone: 'emerald', solid: 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-950' },
  strong: { label: 'Strong', tone: 'sky', solid: 'bg-sky-600 text-white dark:bg-sky-400 dark:text-sky-950' },
  moderate: { label: 'Moderate', tone: 'amber', solid: 'bg-amber-400 text-amber-950 dark:bg-amber-400 dark:text-amber-950' },
  low: { label: 'Low', tone: 'slate', solid: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200' },
}

export const RUN_STATUS_TONE: Record<string, Tone> = {
  running: 'blue',
  succeeded: 'emerald',
  partial: 'amber',
  failed: 'red',
  cancelled: 'zinc',
  queued: 'sky',
  dead: 'red',
  done: 'emerald',
  skipped: 'slate',
}

export const KIND_META: Record<string, { label: string; tone: Tone; help: string }> = {
  fixed: { label: 'Fixed', tone: 'blue', help: 'Verified fact from your profile or approved library answer.' },
  contextual: { label: 'Contextual', tone: 'violet', help: 'Written for this posting from your verified background.' },
  sensitive: { label: 'Sensitive', tone: 'amber', help: 'Sensitive personal data (stored encrypted).' },
  file: { label: 'File', tone: 'sky', help: 'File upload such as your resume.' },
  human: { label: 'Needs you', tone: 'rose', help: 'Requires your answer before submission.' },
  skip: { label: 'Skip', tone: 'gray', help: 'Optional field left blank.' },
}

export function kindMeta(k: string) {
  return KIND_META[k] ?? { label: k, tone: 'slate' as Tone, help: '' }
}

export const LOG_LEVEL_TONE: Record<string, Tone> = {
  debug: 'gray',
  info: 'sky',
  warn: 'amber',
  warning: 'amber',
  error: 'red',
}
