import { useEffect, useState } from 'react'
import { HashRouter, Route, Routes, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AUTH_EVENT } from './api/client'
import { Layout } from './components/Layout'
import { Login } from './components/Login'
import { EmptyState, ButtonLink } from './components/ui'
import OverviewPage from './pages/Overview'
import JobsPage from './pages/Jobs'
import JobDetailPage from './pages/JobDetail'
import PipelinePage from './pages/Pipeline'
import ReviewPage from './pages/Review'
import AutomationPage from './pages/Automation'
import RunsPage from './pages/Runs'
import ProfilePage from './pages/Profile'

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Overview'],
  [/^\/jobs\/\d+/, 'Job detail'],
  [/^\/jobs/, 'Opportunities'],
  [/^\/pipeline/, 'Pipeline'],
  [/^\/review/, 'Review queue'],
  [/^\/automation/, 'Automation'],
  [/^\/runs/, 'Runs'],
  [/^\/profile/, 'Profile & onboarding'],
]

function DocumentTitle() {
  const { pathname } = useLocation()
  useEffect(() => {
    const t = TITLES.find(([re]) => re.test(pathname))?.[1]
    document.title = t ? `${t} · Internship Command Center` : 'Internship Command Center'
  }, [pathname])
  return null
}

export default function App() {
  const [authRequired, setAuthRequired] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    const on = () => setAuthRequired(true)
    window.addEventListener(AUTH_EVENT, on)
    return () => window.removeEventListener(AUTH_EVENT, on)
  }, [])

  if (authRequired) {
    return (
      <Login
        onSuccess={() => {
          setAuthRequired(false)
          qc.resetQueries()
        }}
      />
    )
  }

  return (
    <HashRouter>
      <ScrollToTop />
      <DocumentTitle />
      <Layout>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/automation" element={<AutomationPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route
            path="*"
            element={<EmptyState title="Page not found" description="That page doesn't exist." action={<ButtonLink href="#/">Go to overview</ButtonLink>} />}
          />
        </Routes>
      </Layout>
    </HashRouter>
  )
}
