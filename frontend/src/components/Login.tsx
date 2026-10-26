import { useState, type FormEvent } from 'react'
import { Lock } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import { Button } from './ui'

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/api/login', { method: 'POST', body: { password } })
      setPassword('')
      onSuccess()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-6 sm:p-8" aria-labelledby="login-title">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-white shadow">
            <Lock className="h-6 w-6" aria-hidden />
          </span>
          <h1 id="login-title" className="text-lg font-semibold">
            Summer 2027 Internship Command Center
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Enter the dashboard password to continue.</p>
        </div>
        <label htmlFor="pw" className="label">
          Password
        </label>
        <input
          id="pw"
          type="password"
          autoComplete="current-password"
          className="input mt-1.5"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          required
          aria-invalid={!!error}
          aria-describedby={error ? 'pw-error' : undefined}
        />
        {error && (
          <p id="pw-error" role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="md" className="mt-5 w-full" loading={busy}>
          Sign in
        </Button>
      </form>
    </div>
  )
}
