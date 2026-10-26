import { useEffect, useRef } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  AnswerRow,
  AssistState,
  AssistStatus,
  AutomationSettings,
  BoardRow,
  JobDetail,
  JobsResponse,
  JobSummary,
  MasterResume,
  NotificationRow,
  OverviewResponse,
  PipelineResponse,
  ProfileResponse,
  Question,
  ResumeVersion,
  RunDetail,
  RunLogRow,
  RunSummary,
  StatusResponse,
  TaskRow,
} from './types'

// ------------------------------------------------------------------ queries

export const qk = {
  status: ['status'] as const,
  overview: ['overview'] as const,
  jobs: (params: Record<string, string>) => ['jobs', params] as const,
  job: (id: number) => ['job', id] as const,
  pipeline: ['pipeline'] as const,
  questions: (status: string) => ['questions', status] as const,
  answers: ['answers'] as const,
  settings: ['settings'] as const,
  runs: ['runs'] as const,
  run: (id: number) => ['run', id] as const,
  runLogs: (id: number, level: string, stage: string) => ['runLogs', id, level, stage] as const,
  tasks: ['tasks'] as const,
  profile: ['profile'] as const,
  masterResume: ['masterResume'] as const,
  boards: ['boards'] as const,
  notifications: ['notifications', 'unread'] as const,
}

export function useStatus() {
  return useQuery({
    queryKey: qk.status,
    queryFn: () => api<StatusResponse>('/api/status'),
    refetchInterval: (q) => (q.state.data?.active_run ? 4000 : 20000),
  })
}

export function useOverview() {
  return useQuery({ queryKey: qk.overview, queryFn: () => api<OverviewResponse>('/api/overview'), refetchInterval: 60000 })
}

export function useJobs(params: Record<string, string>, enabled = true) {
  return useQuery({
    queryKey: qk.jobs(params),
    queryFn: () => api<JobsResponse>('/api/jobs', { query: params }),
    placeholderData: keepPreviousData,
    enabled,
  })
}

export function useJob(id: number) {
  return useQuery({ queryKey: qk.job(id), queryFn: () => api<JobDetail>(`/api/jobs/${id}`), enabled: Number.isFinite(id) })
}

export function usePipeline() {
  return useQuery({ queryKey: qk.pipeline, queryFn: () => api<PipelineResponse>('/api/pipeline') })
}

export function useQuestions(status = 'open') {
  return useQuery({ queryKey: qk.questions(status), queryFn: () => api<Question[]>('/api/questions', { query: { status } }) })
}

export function useAnswers() {
  return useQuery({ queryKey: qk.answers, queryFn: () => api<AnswerRow[]>('/api/answers') })
}

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => api<AutomationSettings>('/api/settings') })
}

export function useRuns() {
  return useQuery({
    queryKey: qk.runs,
    queryFn: () => api<RunSummary[]>('/api/runs', { query: { limit: 50 } }),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 4000 : 30000),
  })
}

export function useRun(id: number | null) {
  return useQuery({
    queryKey: qk.run(id ?? -1),
    queryFn: () => api<RunDetail>(`/api/runs/${id}`),
    enabled: id != null,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
  })
}

export function useRunLogs(id: number | null, level: string, stage: string, live: boolean) {
  return useQuery({
    queryKey: qk.runLogs(id ?? -1, level, stage),
    queryFn: () => api<RunLogRow[]>(`/api/runs/${id}/logs`, { query: { level: level || undefined, stage: stage || undefined, limit: 500 } }),
    enabled: id != null,
    placeholderData: keepPreviousData,
    refetchInterval: live ? 3000 : false,
  })
}

export function useTasks() {
  return useQuery({ queryKey: qk.tasks, queryFn: () => api<TaskRow[]>('/api/tasks') })
}

export function useProfile() {
  return useQuery({ queryKey: qk.profile, queryFn: () => api<ProfileResponse>('/api/profile') })
}

export function useMasterResume(enabled = true) {
  return useQuery({
    queryKey: qk.masterResume,
    queryFn: () => api<{ version: number; data: MasterResume }>('/api/master-resume'),
    enabled,
  })
}

export function useBoards(enabled = true) {
  return useQuery({ queryKey: qk.boards, queryFn: () => api<BoardRow[]>('/api/boards'), enabled })
}

export function useNotifications() {
  return useQuery({
    queryKey: qk.notifications,
    queryFn: () => api<NotificationRow[]>('/api/notifications', { query: { unread: true } }),
    refetchInterval: 45000,
  })
}

// ------------------------------------------------------------------ mutations

/** Invalidate everything job-related after a write. */
function useInvalidateJobs() {
  const qc = useQueryClient()
  return (jobId?: number) => {
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: qk.pipeline })
    qc.invalidateQueries({ queryKey: qk.overview })
    qc.invalidateQueries({ queryKey: ['questions'] })
    qc.invalidateQueries({ queryKey: qk.notifications })
    if (jobId != null) qc.invalidateQueries({ queryKey: qk.job(jobId) })
  }
}

export function useJobAction<TBody = void>(action: string, opts: { silent?: boolean } = {}) {
  const invalidate = useInvalidateJobs()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body?: TBody }) =>
      api<JobSummary>(`/api/jobs/${id}/${action}`, { method: 'POST', body: body ?? undefined }),
    onSuccess: (_d, v) => invalidate(v.id),
    meta: { silent: opts.silent },
  })
}

export function useSubmitNow() {
  const invalidate = useInvalidateJobs()
  return useMutation({
    mutationFn: (id: number) => api<{ submitted: string | boolean; reasons?: string[] }>(`/api/jobs/${id}/submit-now`, { method: 'POST' }),
    onSuccess: (_d, id) => invalidate(id),
    meta: { silent: true },
  })
}

export function useRegenerateResume() {
  const invalidate = useInvalidateJobs()
  return useMutation({
    mutationFn: (id: number) => api<ResumeVersion>(`/api/jobs/${id}/regenerate-resume`, { method: 'POST' }),
    onSuccess: (_d, id) => invalidate(id),
  })
}

export function useSaveNotes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, notes }: { id: number; notes: string }) => api(`/api/jobs/${id}/notes`, { method: 'POST', body: { notes } }),
    onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: qk.job(v.id) }),
  })
}

export function useAnswerQuestion() {
  const invalidate = useInvalidateJobs()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ qid, answer, save_to_library }: { qid: number; jobId?: number; answer: string; save_to_library: boolean }) =>
      api<Question>(`/api/questions/${qid}/answer`, { method: 'POST', body: { answer, save_to_library } }),
    onSuccess: (_d, v) => {
      invalidate(v.jobId)
      qc.invalidateQueries({ queryKey: ['job'] })
      qc.invalidateQueries({ queryKey: qk.answers })
    },
  })
}

export function useDismissQuestion() {
  const invalidate = useInvalidateJobs()
  return useMutation({
    mutationFn: ({ qid }: { qid: number; jobId?: number }) => api<Question>(`/api/questions/${qid}/dismiss`, { method: 'POST' }),
    onSuccess: (_d, v) => invalidate(v.jobId),
  })
}

export function useStartRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { dry_run: boolean; stages?: string[] }) => api('/api/runs', { method: 'POST', body }),
    onSuccess: () => {
      // The run starts in a background thread; poll status shortly after.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: qk.status })
        qc.invalidateQueries({ queryKey: qk.runs })
      }, 800)
    },
  })
}

export function useAutomationAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (action: 'start' | 'stop' | 'pause' | 'resume' | 'enable' | 'disable') =>
      api<Record<string, unknown>>(`/api/automation/${action}`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.status })
      qc.invalidateQueries({ queryKey: qk.settings })
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: qk.status })
        qc.invalidateQueries({ queryKey: qk.runs })
      }, 800)
    },
  })
}

export function usePatchSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<AutomationSettings>) => api<AutomationSettings>('/api/settings', { method: 'PATCH', body: patch }),
    onSuccess: (data) => {
      qc.setQueryData(qk.settings, data)
      qc.invalidateQueries({ queryKey: qk.status })
    },
  })
}

export function usePatchProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) => api<ProfileResponse>('/api/profile', { method: 'PATCH', body: patch }),
    onSuccess: (data) => {
      qc.setQueryData(qk.profile, data)
      qc.invalidateQueries({ queryKey: qk.status })
      qc.invalidateQueries({ queryKey: qk.answers })
    },
  })
}

export function usePatchAnswer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, patch }: { key: string; patch: { approved?: boolean; answer?: string } }) =>
      api(`/api/answers/${encodeURIComponent(key)}`, { method: 'PATCH', body: patch }),
    onSettled: () => qc.invalidateQueries({ queryKey: qk.answers }),
  })
}

export function useDeleteAnswer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => api(`/api/answers/${encodeURIComponent(key)}`, { method: 'DELETE' }),
    onSettled: () => qc.invalidateQueries({ queryKey: qk.answers }),
  })
}

export function usePatchBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) => api(`/api/boards/${id}`, { method: 'PATCH', body: { active } }),
    onMutate: async ({ id, active }) => {
      await qc.cancelQueries({ queryKey: qk.boards })
      const prev = qc.getQueryData<BoardRow[]>(qk.boards)
      qc.setQueryData<BoardRow[]>(qk.boards, (rows) => rows?.map((b) => (b.id === id ? { ...b, active } : b)))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.boards, ctx.prev)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.boards }),
  })
}

export function useAddBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { platform: string; token: string; company?: string; metro?: string }) =>
      api<{ id: number }>('/api/boards', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.boards }),
  })
}

export function useReadAllNotifications() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api('/api/notifications/read-all', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}

export function useDeleteData() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { confirm: string; scope: 'jobs' | 'everything' }) =>
      api<{ ok: boolean; scope: string }>('/api/data/delete', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries(),
  })
}

// ------------------------------------------------------------------ assisted finish

const ASSIST_ACTIVE: AssistState[] = ['starting', 'filling', 'waiting']

export function useAssistStatus() {
  const invalidate = useInvalidateJobs()
  const last = useRef<AssistState | null>(null)
  const q = useQuery({
    queryKey: ['assist'],
    queryFn: () => api<AssistStatus>('/api/assist'),
    refetchInterval: (query) => (query.state.data && ASSIST_ACTIVE.includes(query.state.data.state) ? 2000 : 15000),
  })
  const lastJob = useRef<number | null>(null)
  // when a session ends (or Finish all moves to the next application), refresh the job data it changed
  useEffect(() => {
    const st = q.data?.state ?? null
    const job = q.data?.job_id ?? null
    if (last.current && ASSIST_ACTIVE.includes(last.current) && st && !ASSIST_ACTIVE.includes(st)) {
      invalidate(job ?? undefined)
    } else if (lastJob.current != null && job !== lastJob.current) {
      invalidate(lastJob.current)
    }
    last.current = st
    lastJob.current = job
  }, [q.data?.state, q.data?.job_id]) // eslint-disable-line react-hooks/exhaustive-deps
  return q
}

export function useAssistStart() {
  const qc = useQueryClient()
  const invalidate = useInvalidateJobs()
  return useMutation({
    mutationFn: (id: number) => api<AssistStatus>(`/api/jobs/${id}/assist`, { method: 'POST' }),
    onSuccess: (data, id) => {
      qc.setQueryData(['assist'], data)
      invalidate(id)
    },
  })
}

export function useAssistQueueStart() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<AssistStatus>('/api/assist/queue', { method: 'POST' }),
    onSuccess: (data) => qc.setQueryData(['assist'], data),
  })
}

export function useAssistSkip() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ skipped: boolean }>('/api/assist/skip', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assist'] }),
  })
}

export function useAssistCancel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ cancelled: boolean }>('/api/assist/cancel', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assist'] }),
  })
}
