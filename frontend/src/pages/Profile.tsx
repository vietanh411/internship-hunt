import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Circle, Database, Download, FileUser, Library, ListChecks, Pencil, Save, ShieldCheck, Trash2, UserRound, X } from 'lucide-react'
import { useAnswers, useDeleteAnswer, useDeleteData, useMasterResume, usePatchAnswer, usePatchProfile, useProfile, useStatus } from '../api/hooks'
import type { AnswerRow, MasterResume, OnboardingItem, Profile } from '../api/types'
import { Badge, Button, ButtonLink, Callout, Card, Chip, Dialog, EmptyState, ErrorState, Field, PageHeader, RichText, Skeleton, SkeletonRows, Tabs, TagInput, Toggle, cx } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { DASH, fmtRelative, humanize, pathToObject } from '../lib/format'
import { kindMeta } from '../lib/status'

type Tab = 'onboarding' | 'details' | 'answers' | 'resume' | 'data'

// ------------------------------------------------------------------ onboarding

type InputKind = 'yesno' | 'eeo' | 'text' | 'url' | 'date' | 'number'
const FIELD_KIND: Record<string, InputKind> = {
  'attestations.is_over_18': 'yesno',
  'attestations.has_relatives_at_employer': 'yesno',
  'attestations.subject_to_noncompete': 'yesno',
  'eeo.policy': 'eeo',
  'contact.github_url': 'url',
  'contact.portfolio_url': 'url',
  'availability.latest_end_date': 'date',
  'preferences.min_hourly_rate': 'number',
}

function kindFor(item: OnboardingItem): InputKind {
  if (FIELD_KIND[item.path]) return FIELD_KIND[item.path]
  if (typeof item.value === 'boolean') return 'yesno'
  if (typeof item.value === 'number') return 'number'
  if (item.path.endsWith('_date')) return 'date'
  if (item.path.endsWith('_url')) return 'url'
  return 'text'
}

function toInput(v: unknown, kind: InputKind): string {
  if (v === null || v === undefined) return ''
  if (kind === 'yesno') return v === true ? 'yes' : v === false ? 'no' : ''
  return String(v)
}

function fromInput(s: string, kind: InputKind): unknown {
  if (kind === 'yesno') return s === 'yes' ? true : s === 'no' ? false : null
  if (s.trim() === '') return null
  if (kind === 'number') return Number(s)
  return s.trim()
}

function OnboardingRow({ item }: { item: OnboardingItem }) {
  const kind = kindFor(item)
  const [val, setVal] = useState(toInput(item.value, kind))
  const patch = usePatchProfile()
  const push = useToast()
  useEffect(() => setVal(toInput(item.value, kind)), [item.value, kind])
  const dirty = val !== toInput(item.value, kind)
  const id = `ob-${item.path.replace(/\./g, '-')}`
  const save = (v = val) =>
    patch.mutate(pathToObject(item.path, fromInput(v, kind)), { onSuccess: () => push('success', 'Saved', item.label) })
  const answeredNo = !item.complete && item.value === false && kind === 'yesno'
  const immediate = kind === 'yesno' || kind === 'eeo'

  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start">
      <div className="flex min-w-0 flex-1 gap-3">
        {item.complete ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="Complete" />
        ) : answeredNo ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" aria-label="Answered" />
        ) : (
          <Circle className={cx('mt-0.5 h-5 w-5 shrink-0', item.required ? 'text-amber-500' : 'text-slate-300 dark:text-slate-600')} aria-label="Incomplete" />
        )}
        <div className="min-w-0">
          <label htmlFor={id} className="text-sm font-medium text-slate-900 dark:text-slate-100">
            {item.label}
          </label>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            {item.required ? <Badge tone="amber">Required for auto-apply</Badge> : <Badge tone="slate">Optional</Badge>}
            {answeredNo && <span className="text-xs text-slate-500 dark:text-slate-400">Answered “No” (the checklist only counts a “Yes” or text value as complete)</span>}
          </div>
          {item.help && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.help}</p>}
        </div>
      </div>
      <div className="flex w-full gap-2 sm:w-72 sm:shrink-0">
        {kind === 'yesno' ? (
          <select
            id={id}
            className="input"
            value={val}
            disabled={patch.isPending}
            onChange={(e) => {
              setVal(e.target.value)
              save(e.target.value)
            }}
          >
            <option value="">Not answered</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        ) : kind === 'eeo' ? (
          <select
            id={id}
            className="input"
            value={val || 'ask'}
            disabled={patch.isPending}
            onChange={(e) => {
              setVal(e.target.value)
              save(e.target.value)
            }}
          >
            <option value="ask">Ask me each time</option>
            <option value="decline">Decline to self-identify</option>
          </select>
        ) : (
          <>
            <input
              id={id}
              className="input"
              type={kind === 'date' ? 'date' : kind === 'number' ? 'number' : kind === 'url' ? 'url' : 'text'}
              inputMode={kind === 'number' ? 'decimal' : undefined}
              value={val}
              onChange={(e) => setVal(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && dirty && save()}
              placeholder={kind === 'url' ? 'https://' : undefined}
            />
            {!immediate && (
              <Button variant={dirty ? 'primary' : 'secondary'} size="md" disabled={!dirty} loading={patch.isPending} onClick={() => save()} aria-label={`Save ${item.label}`} icon={<Save className="h-4 w-4" />} />
            )}
          </>
        )}
      </div>
    </li>
  )
}

function yn(v: unknown, yes = 'Yes', no = 'No'): string {
  return v === true ? yes : v === false ? no : 'Not set'
}

function WorkAuthConfirm({ profile, item }: { profile: Profile; item: OnboardingItem | undefined }) {
  const wa = (profile.work_authorization ?? {}) as Record<string, unknown>
  const patch = usePatchProfile()
  const push = useToast()
  const confirmed = wa.confirmed === true
  const statements: [string, string][] = [
    ['Visa status', wa.visa_status ? String(wa.visa_status) : 'Not set'],
    ['Authorized to work in the U.S.', wa.authorized_to_work_us === true ? `Yes, via ${[wa.cpt_eligible && 'CPT', wa.opt_eligible && 'OPT'].filter(Boolean).join(' / ') || 'CPT / OPT'}` : yn(wa.authorized_to_work_us)],
    ['Will require visa sponsorship now or in the future', yn(wa.requires_sponsorship_now_or_future)],
    ['U.S. citizen', yn(wa.us_citizen)],
    ['U.S. permanent resident (green card holder)', yn(wa.permanent_resident)],
  ]
  if ('security_clearance' in wa) statements.push(['Holds a security clearance', yn(wa.security_clearance)])
  return (
    <div className={cx('rounded-xl border-2 p-4', confirmed ? 'border-emerald-300 bg-emerald-50/50 dark:border-emerald-500/40 dark:bg-emerald-500/5' : 'border-amber-300 bg-amber-50/60 dark:border-amber-500/40 dark:bg-amber-500/5')}>
      <div className="flex items-start gap-3">
        <ShieldCheck className={cx('mt-0.5 h-5 w-5 shrink-0', confirmed ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400')} aria-hidden />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Work-authorization answers</h3>
          <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-300">
            These exact statements are given on every application that asks. Automatic submission stays off until you confirm them.
          </p>
          {item?.help && (
            <p className="mt-2 rounded-md bg-white/70 px-3 py-2 text-sm font-medium text-slate-800 dark:bg-slate-900/60 dark:text-slate-100">{item.help}</p>
          )}
          <dl className="mt-3 divide-y divide-slate-200/70 rounded-lg border border-slate-200 bg-white dark:divide-slate-700 dark:border-slate-700 dark:bg-slate-900">
            {statements.map(([q, a]) => (
              <div key={q} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-3 py-2 text-sm">
                <dt className="text-slate-600 dark:text-slate-300">{q}</dt>
                <dd className="font-semibold text-slate-900 dark:text-white">{a}</dd>
              </div>
            ))}
          </dl>
          <label className="mt-3 flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500 dark:border-slate-600 dark:bg-slate-800"
              checked={confirmed}
              disabled={patch.isPending}
              onChange={(e) =>
                patch.mutate(
                  { work_authorization: { confirmed: e.target.checked } },
                  { onSuccess: () => push('success', e.target.checked ? 'Work authorization confirmed' : 'Confirmation withdrawn') },
                )
              }
            />
            <span className="font-medium text-slate-900 dark:text-slate-100">
              I confirm these statements are accurate and may be used on my applications.
            </span>
          </label>
        </div>
      </div>
    </div>
  )
}

function Onboarding({ data }: { data: { profile: Profile; onboarding: OnboardingItem[]; auto_apply_blockers: string[] } }) {
  const wa = data.onboarding.find((i) => i.path === 'work_authorization.confirmed')
  const rest = data.onboarding.filter((i) => i.path !== 'work_authorization.confirmed')
  const done = data.onboarding.filter((i) => i.complete).length
  const pct = data.onboarding.length ? Math.round((done / data.onboarding.length) * 100) : 0
  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-white">
              {done} of {data.onboarding.length} items complete
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {data.auto_apply_blockers.length ? `Blocking automatic submission: ${data.auto_apply_blockers.join(', ')}` : 'Every item required for automatic submission is complete.'}
            </p>
          </div>
          {data.auto_apply_blockers.length ? <Badge tone="amber">{data.auto_apply_blockers.length} required left</Badge> : <Badge tone="emerald">Ready for auto-apply</Badge>}
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Onboarding progress">
          <div className="h-full rounded-full bg-indigo-600 transition-all dark:bg-indigo-400" style={{ width: `${pct}%` }} />
        </div>
      </Card>
      <WorkAuthConfirm profile={data.profile} item={wa} />
      <Card title="Checklist" icon={<ListChecks className="h-4 w-4 text-slate-400" />}>
        <ul className="-my-4 divide-y divide-slate-100 dark:divide-slate-800">
          {rest.map((i) => (
            <OnboardingRow key={i.path} item={i} />
          ))}
        </ul>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ profile sections

const LABELS: Record<string, string> = {
  linkedin_url: 'LinkedIn URL',
  github_url: 'GitHub URL',
  portfolio_url: 'Portfolio URL',
  address_line1: 'Street address',
  postal_code: 'ZIP / postal code',
  current_gpa: 'Current GPA',
  undergrad_gpa: 'Undergraduate GPA',
  how_did_you_hear: 'How did you hear (default answer)',
  min_hourly_rate: 'Minimum hourly rate (USD)',
}
const SENSITIVE = new Set(['contact.phone', 'contact.address_line1', 'contact.postal_code'])
const NUMERIC = new Set(['preferences.min_hourly_rate'])

function SectionEditor({ section, title, value, encryption }: { section: string; title: string; value: Record<string, unknown>; encryption: boolean }) {
  const [draft, setDraft] = useState<Record<string, unknown>>(value)
  const patch = usePatchProfile()
  const push = useToast()
  useEffect(() => setDraft(value), [value])
  const changed = Object.keys(draft).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(value[k]))
  const set = (k: string, v: unknown) => setDraft((d) => ({ ...d, [k]: v }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const out: Record<string, unknown> = {}
    for (const k of changed) out[k] = draft[k]
    patch.mutate({ [section]: out }, { onSuccess: () => push('success', `${title} saved`) })
  }

  return (
    <Card title={title}>
      <form onSubmit={submit}>
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(draft).map(([k, v]) => {
            const path = `${section}.${k}`
            const id = `pf-${section}-${k}`
            const label = LABELS[k] ?? humanize(k)
            const sens = SENSITIVE.has(path)
            const hint = sens ? (encryption ? 'Stored encrypted.' : 'Sensitive — set HUNT_SECRET_KEY to store it encrypted.') : undefined
            const orig = value[k]
            if (typeof orig === 'boolean' || typeof v === 'boolean')
              return (
                <div key={k} className="sm:col-span-1">
                  <Toggle id={id} label={label} checked={!!v} onChange={(nv) => set(k, nv)} />
                </div>
              )
            if (Array.isArray(orig) || Array.isArray(v))
              return (
                <Field key={k} label={label} htmlFor={id} className="sm:col-span-2">
                  <TagInput id={id} value={(v as string[]) ?? []} onChange={(nv) => set(k, nv)} />
                </Field>
              )
            const numeric = typeof orig === 'number' || NUMERIC.has(path)
            const type = numeric ? 'number' : k.endsWith('_date') ? 'date' : k.endsWith('_url') ? 'url' : k === 'email' ? 'email' : 'text'
            return (
              <Field key={k} label={label} htmlFor={id} hint={hint}>
                <input
                  id={id}
                  className="input"
                  type={type}
                  value={v === null || v === undefined ? '' : String(v)}
                  onChange={(e) => set(k, e.target.value === '' ? null : numeric ? Number(e.target.value) : e.target.value)}
                />
              </Field>
            )
          })}
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          {changed.length > 0 && (
            <Button onClick={() => setDraft(value)} icon={<X className="h-4 w-4" />}>
              Discard
            </Button>
          )}
          <Button type="submit" variant="primary" disabled={!changed.length} loading={patch.isPending} icon={<Save className="h-4 w-4" />}>
            Save {title.toLowerCase()}
          </Button>
        </div>
      </form>
    </Card>
  )
}

function ExtraSkills({ skills }: { skills: string[] }) {
  const [draft, setDraft] = useState(skills)
  const patch = usePatchProfile()
  const push = useToast()
  useEffect(() => setDraft(skills), [skills])
  const dirty = JSON.stringify(draft) !== JSON.stringify(skills)
  return (
    <Card title="Confirmed extra skills" subtitle="Skills you genuinely have that are not on the master resume.">
      <Callout tone="amber" icon={<AlertTriangle className="h-4 w-4" />} className="mb-3">
        Only add skills you really hold. Tailoring treats these as verified and may put them on your resume when a posting asks for them.
      </Callout>
      <TagInput value={draft} onChange={setDraft} ariaLabel="Confirmed extra skills" placeholder="e.g. Spark" />
      <div className="mt-3 flex justify-end gap-2">
        {dirty && <Button onClick={() => setDraft(skills)}>Discard</Button>}
        <Button
          variant="primary"
          disabled={!dirty}
          loading={patch.isPending}
          icon={<Save className="h-4 w-4" />}
          onClick={() => patch.mutate({ confirmed_extra_skills: draft }, { onSuccess: () => push('success', 'Extra skills saved') })}
        >
          Save skills
        </Button>
      </div>
    </Card>
  )
}

function Details({ profile }: { profile: Profile }) {
  const { data: status } = useStatus()
  const enc = !!status?.encryption_enabled
  const sections: [string, string][] = [
    ['identity', 'Identity'],
    ['contact', 'Contact'],
    ['education', 'Education'],
    ['availability', 'Availability'],
    ['preferences', 'Preferences'],
  ]
  return (
    <div className="space-y-6">
      {sections.map(([k, t]) =>
        profile[k] && typeof profile[k] === 'object' ? (
          <SectionEditor key={k} section={k} title={t} value={profile[k] as Record<string, unknown>} encryption={enc} />
        ) : (
          <Card key={k} title={t}>
            <p className="text-sm text-slate-500">This section is missing from the profile.</p>
          </Card>
        ),
      )}
      <ExtraSkills skills={Array.isArray(profile.confirmed_extra_skills) ? (profile.confirmed_extra_skills as string[]) : []} />
    </div>
  )
}

// ------------------------------------------------------------------ answer library

function AnswerItem({ a }: { a: AnswerRow }) {
  const approve = usePatchAnswer()
  const del = useDeleteAnswer()
  const push = useToast()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(a.answer ?? '')
  const [confirmDel, setConfirmDel] = useState(false)
  const km = kindMeta(a.kind)
  const optimistic = approve.isPending ? (approve.variables?.patch.approved ?? a.approved) : a.approved
  return (
    <li className="py-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-slate-900 dark:text-slate-100">{a.label}</span>
            <Badge tone={km.tone} title={km.help}>
              {km.label}
            </Badge>
            <Badge tone={a.source === 'user' ? 'indigo' : a.source === 'profile' ? 'teal' : 'slate'}>{a.source}</Badge>
            {a.sensitive && <Badge tone="amber">sensitive</Badge>}
          </div>
          {editing ? (
            <div className="mt-2 flex gap-2">
              <label htmlFor={`ans-${a.key}`} className="sr-only">
                Answer
              </label>
              <input id={`ans-${a.key}`} className="input" value={text} onChange={(e) => setText(e.target.value)} />
              <Button
                variant="primary"
                size="md"
                loading={approve.isPending}
                onClick={() =>
                  approve.mutate(
                    { key: a.key, patch: { answer: text } },
                    {
                      onSuccess: () => {
                        setEditing(false)
                        push('success', 'Answer updated')
                      },
                    },
                  )
                }
              >
                Save
              </Button>
              <Button size="md" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <p className="mt-1 break-words text-sm text-slate-600 dark:text-slate-300">
              {a.answer ? a.answer : <span className="text-slate-400">{a.kind === 'contextual' ? 'Written per posting' : a.kind === 'human' ? 'Always asks you' : DASH}</span>}
            </p>
          )}
          <p className="mt-0.5 text-xs text-slate-400">
            {a.key}
            {a.updated_at ? ` · updated ${fmtRelative(a.updated_at)}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <Toggle
            size="sm"
            checked={optimistic}
            ariaLabel={`Approve “${a.label}” for automatic use`}
            disabled={approve.isPending}
            onChange={(v) => approve.mutate({ key: a.key, patch: { approved: v } }, { onSuccess: () => push('success', v ? 'Answer approved' : 'Approval removed') })}
          />
          <span className="w-16 text-xs text-slate-500 dark:text-slate-400">{optimistic ? 'Approved' : 'Not approved'}</span>
          {a.source === 'user' && !editing && (
            <>
              <Button size="xs" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(true)} aria-label={`Edit answer for ${a.label}`} />
              <Button size="xs" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5 text-red-600" />} onClick={() => setConfirmDel(true)} aria-label={`Delete answer for ${a.label}`} />
            </>
          )}
        </div>
      </div>
      <Dialog
        open={confirmDel}
        onClose={() => setConfirmDel(false)}
        title="Delete saved answer?"
        size="sm"
        footer={
          <>
            <Button onClick={() => setConfirmDel(false)}>Cancel</Button>
            <Button
              variant="danger"
              loading={del.isPending}
              onClick={() =>
                del.mutate(a.key, {
                  onSuccess: () => {
                    setConfirmDel(false)
                    push('success', 'Answer deleted')
                  },
                })
              }
            >
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600 dark:text-slate-300">
          “{a.label}” will no longer be filled automatically; matching questions will come back to your review queue.
        </p>
      </Dialog>
    </li>
  )
}

function Answers() {
  const { data, isLoading, error, refetch } = useAnswers()
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const kinds = useMemo(() => [...new Set((data ?? []).map((a) => a.kind))], [data])
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return (data ?? []).filter((a) => (!kind || a.kind === kind) && (!ql || `${a.label} ${a.answer ?? ''} ${a.key}`.toLowerCase().includes(ql)))
  }, [data, q, kind])
  return (
    <Card
      title="Answer library"
      icon={<Library className="h-4 w-4 text-slate-400" />}
      subtitle="Reusable screening answers. Approved fixed answers are filled automatically; profile-derived answers are edited in your profile, and work-authorization answers are approved by the confirmation in Onboarding."
    >
      <div className="mb-2 flex flex-wrap gap-2">
        <label htmlFor="ans-q" className="sr-only">
          Search answers
        </label>
        <input id="ans-q" type="search" className="input max-w-xs" placeholder="Search questions and answers…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label htmlFor="ans-kind" className="sr-only">
          Kind
        </label>
        <select id="ans-kind" className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {kindMeta(k).label}
            </option>
          ))}
        </select>
      </div>
      {error && !data ? (
        <ErrorState error={error} onRetry={() => refetch()} compact />
      ) : isLoading || !data ? (
        <SkeletonRows rows={5} />
      ) : !rows.length ? (
        <EmptyState compact icon={<Library className="h-5 w-5" />} title={data.length ? 'No answers match' : 'The library is empty'} description={data.length ? undefined : 'Answers you save from the review queue are added here.'} />
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map((a) => (
            <AnswerItem key={a.key} a={a} />
          ))}
        </ul>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ master resume

function ResumeSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="border-b border-slate-300 pb-1 text-xs font-bold uppercase tracking-[0.12em] text-slate-700 dark:border-slate-600 dark:text-slate-300">{title}</h3>
      <div className="mt-3 space-y-4">{children}</div>
    </section>
  )
}

function MasterResumeView() {
  const { data, isLoading, error, refetch } = useMasterResume()
  if (error && !data) return <ErrorState error={error} onRetry={() => refetch()} />
  if (isLoading || !data) return <Skeleton className="h-[40rem] w-full rounded-xl" />
  const r: MasterResume = data.data ?? {}
  const b = r.basics ?? {}
  return (
    <Card
      title="Master resume"
      icon={<FileUser className="h-4 w-4 text-slate-400" />}
      subtitle={`Version ${data.version} · read-only source of truth. Tailoring may reorder and reword bullets; the fact guard rejects anything not present here.`}
    >
      <article className="mx-auto max-w-3xl rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-950 sm:p-8">
        <header className="text-center">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">{b.name ?? DASH}</h2>
          <p className="mt-1 flex flex-wrap justify-center gap-x-3 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
            {b.phone && <span>{b.phone}</span>}
            {b.email && <a className="link" href={`mailto:${b.email}`}>{b.email}</a>}
            {b.linkedin_url && (
              <a className="link" href={b.linkedin_url} target="_blank" rel="noopener noreferrer">
                {b.linkedin_label ?? 'LinkedIn'}
              </a>
            )}
          </p>
        </header>
        {!!r.education?.length && (
          <ResumeSection title="Education">
            {r.education.map((e, i) => (
              <div key={e.id ?? i} className="flex flex-wrap justify-between gap-x-4 text-sm">
                <div>
                  <p className="font-semibold text-slate-900 dark:text-white">{e.school}</p>
                  <p className="italic text-slate-600 dark:text-slate-300">
                    {e.degree}
                    {e.gpa ? ` · GPA ${e.gpa}` : ''}
                  </p>
                </div>
                <div className="text-right text-slate-600 dark:text-slate-300">
                  <p>{e.location}</p>
                  <p className="italic">{e.dates}</p>
                </div>
              </div>
            ))}
          </ResumeSection>
        )}
        {!!r.experience?.length && (
          <ResumeSection title="Work experience">
            {r.experience.map((e) => (
              <div key={e.id} className="text-sm">
                <div className="flex flex-wrap justify-between gap-x-4">
                  <p className="font-semibold text-slate-900 dark:text-white">{e.org}</p>
                  <p className="text-slate-600 dark:text-slate-300">{e.location}</p>
                </div>
                <div className="flex flex-wrap justify-between gap-x-4 italic text-slate-600 dark:text-slate-300">
                  <p>{e.title}</p>
                  <p>{e.dates}</p>
                </div>
                <ul className="mt-1.5 list-disc space-y-1 pl-5 text-slate-700 dark:text-slate-300">
                  {e.bullets.map((bl) => (
                    <li key={bl.id}>
                      <RichText text={bl.text} />
                    </li>
                  ))}
                </ul>
                {!!e.tech?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {e.tech.map((t) => (
                      <Chip key={t}>{t}</Chip>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </ResumeSection>
        )}
        {!!r.projects?.length && (
          <ResumeSection title="Projects">
            {r.projects.map((p) => (
              <div key={p.id} className="text-sm">
                <p>
                  <span className="font-semibold text-slate-900 dark:text-white">{p.name}</span>
                  {p.context && <span className="italic text-slate-600 dark:text-slate-300"> · {p.context}</span>}
                </p>
                <ul className="mt-1.5 list-disc space-y-1 pl-5 text-slate-700 dark:text-slate-300">
                  {p.bullets.map((bl) => (
                    <li key={bl.id}>
                      <RichText text={bl.text} />
                    </li>
                  ))}
                </ul>
                {!!p.tech?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {p.tech.map((t) => (
                      <Chip key={t}>{t}</Chip>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </ResumeSection>
        )}
        {!!r.skills?.length && (
          <ResumeSection title="Technical skills">
            <dl className="space-y-1 text-sm">
              {r.skills.map((s) => (
                <div key={s.category}>
                  <dt className="inline font-semibold text-slate-900 dark:text-white">{s.category}: </dt>
                  <dd className="inline text-slate-700 dark:text-slate-300">{s.items.join(', ')}</dd>
                </div>
              ))}
            </dl>
          </ResumeSection>
        )}
      </article>
    </Card>
  )
}

// ------------------------------------------------------------------ data controls

function DataControls() {
  const [typed, setTyped] = useState('')
  const [scope, setScope] = useState<'jobs' | 'everything'>('jobs')
  const del = useDeleteData()
  const push = useToast()
  return (
    <div className="space-y-6">
      <Card title="Export" icon={<Download className="h-4 w-4 text-slate-400" />}>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Download a ZIP with every job (including match details and application plans), your profile, master resume, answer library, audit log, and every tailored resume PDF.
        </p>
        <ButtonLink href="/api/export" download className="mt-3" variant="primary" icon={<Download className="h-4 w-4" />}>
          Export all data
        </ButtonLink>
      </Card>
      <Card title="Delete data" icon={<Trash2 className="h-4 w-4 text-red-500" />} className="border-red-200 dark:border-red-500/30">
        <div className="space-y-4">
          <fieldset>
            <legend className="label">What to delete</legend>
            <div className="mt-2 space-y-2">
              <label className="flex items-start gap-2.5 text-sm">
                <input type="radio" name="scope" className="mt-0.5 h-4 w-4 text-red-600 focus:ring-red-500" checked={scope === 'jobs'} onChange={() => setScope('jobs')} />
                <span>
                  <span className="font-medium text-slate-900 dark:text-white">Jobs and applications</span>
                  <span className="block text-slate-500 dark:text-slate-400">Jobs, resumes, applications, questions, notifications, tasks and logs. Keeps your profile, answer library and run history.</span>
                </span>
              </label>
              <label className="flex items-start gap-2.5 text-sm">
                <input type="radio" name="scope" className="mt-0.5 h-4 w-4 text-red-600 focus:ring-red-500" checked={scope === 'everything'} onChange={() => setScope('everything')} />
                <span>
                  <span className="font-medium text-slate-900 dark:text-white">Everything</span>
                  <span className="block text-slate-500 dark:text-slate-400">Also removes run history, your saved answers and profile edits (the profile is re-imported from config/profile.yaml).</span>
                </span>
              </label>
            </div>
          </fieldset>
          <Field label={<>Type <code className="font-mono font-bold">DELETE</code> to confirm</>} htmlFor="del-confirm">
            <input id="del-confirm" className="input max-w-xs font-mono" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </Field>
          <Button
            variant="danger"
            icon={<Trash2 className="h-4 w-4" />}
            disabled={typed !== 'DELETE'}
            loading={del.isPending}
            onClick={() =>
              del.mutate(
                { confirm: typed, scope },
                {
                  onSuccess: (r) => {
                    setTyped('')
                    push('success', 'Data deleted', `Scope: ${r.scope}`)
                  },
                },
              )
            }
          >
            Permanently delete
          </Button>
        </div>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ page

export default function ProfilePage() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'onboarding'
  const { data, isLoading, error, refetch } = useProfile()
  const blockers = data?.auto_apply_blockers.length ?? null
  const tabs: { id: Tab; label: ReactNode; count?: number | null }[] = [
    { id: 'onboarding', label: 'Onboarding', count: blockers || null },
    { id: 'details', label: 'Profile details' },
    { id: 'answers', label: 'Answer library' },
    { id: 'resume', label: 'Master resume' },
    { id: 'data', label: 'Data controls' },
  ]
  const needsProfile = tab === 'onboarding' || tab === 'details'
  return (
    <div>
      <PageHeader title="Profile & onboarding" description="The facts used verbatim on applications. Never enter anything that isn't true." />
      <div className="mb-5">
        <Tabs tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t }, { replace: true })} ariaLabel="Profile sections" />
      </div>
      {needsProfile &&
        (error && !data ? (
          <div className="card">
            <ErrorState error={error} onRetry={() => refetch()} />
          </div>
        ) : isLoading || !data ? (
          <Skeleton className="h-96 w-full rounded-xl" />
        ) : !Object.keys(data.profile).length ? (
          <div className="card">
            <EmptyState icon={<UserRound className="h-5 w-5" />} title="No profile yet" description="Run `python -m hunt init` to import config/profile.yaml." />
          </div>
        ) : tab === 'onboarding' ? (
          <Onboarding data={data} />
        ) : (
          <Details profile={data.profile} />
        ))}
      {tab === 'answers' && <Answers />}
      {tab === 'resume' && <MasterResumeView />}
      {tab === 'data' && <DataControls />}
      {tab === 'data' && (
        <p className="mt-4 flex items-center gap-1.5 text-xs text-slate-400">
          <Database className="h-3.5 w-3.5" /> Deletion cannot be undone. Export first if you might need the data.
        </p>
      )}
    </div>
  )
}
