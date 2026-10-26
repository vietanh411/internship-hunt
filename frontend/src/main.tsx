import React from 'react'
import ReactDOM from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ApiError, errorMessage } from './api/client'
import { ThemeProvider } from './lib/theme'
import { ToastProvider, toast } from './components/ui/Toast'
import './index.css'

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (err, query) => {
      // Background refetch failures surface as toasts; first-load failures render inline.
      if (err instanceof ApiError && err.status === 401) return
      if (query.state.data !== undefined) toast('error', 'Refresh failed', errorMessage(err))
    },
  }),
  mutationCache: new MutationCache({
    onError: (err, _vars, _ctx, mutation) => {
      if (err instanceof ApiError && err.status === 401) return
      if (mutation.meta?.silent) return
      toast('error', 'Action failed', errorMessage(err))
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (count, err) => !(err instanceof ApiError && [400, 401, 403, 404, 409].includes(err.status)) && count < 1,
      refetchOnWindowFocus: true,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ToastProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
