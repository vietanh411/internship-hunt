import { humanize } from './format'

// Most informative counters per pipeline stage, shown first in run summaries.
const STAGE_KEYS: Record<string, string[]> = {
  discovery: ['new_jobs', 'boards_polled', 'merged_duplicates'],
  verification: ['active', 'expired', 'unverifiable'],
  deduplication: ['merged'],
  eligibility: ['eligible', 'review', 'ineligible'],
  matching: ['excellent', 'strong', 'moderate', 'low'],
  resume_generation: ['generated', 'ats_failed', 'task_failures'],
  application: ['prepared', 'submitted', 'blocked'],
  confirmation: ['matched', 'checked'],
  reporting: ['qualified', 'resumes_generated', 'confirmed_submissions'],
}

export function stageHighlights(stage: string, result: unknown, max = 3): string[] {
  if (!result || typeof result !== 'object') return typeof result === 'string' ? [result] : []
  const r = result as Record<string, unknown>
  if (typeof r.skipped === 'string') return [`skipped: ${r.skipped}`]
  if (typeof r.error === 'string') return [`error: ${r.error}`]
  const prefer = STAGE_KEYS[stage] ?? []
  const keys = [
    ...prefer.filter((k) => typeof r[k] === 'number'),
    ...Object.keys(r).filter((k) => !prefer.includes(k) && typeof r[k] === 'number' && !k.startsWith('target') && !k.startsWith('cat:')),
  ]
  return keys.slice(0, max).map((k) => `${(r[k] as number).toLocaleString()} ${humanize(k).toLowerCase()}`)
}

const TRIGGERS: Record<string, string> = {
  cli: 'CLI',
  schedule: 'Scheduled',
  manual: 'Manual',
  github: 'GitHub Actions',
  'manual-resume': 'Resume regeneration',
  'manual-submit': 'Submit now',
}

export function triggerLabel(t: string | null | undefined): string {
  if (!t) return '—'
  return TRIGGERS[t] ?? humanize(t)
}
