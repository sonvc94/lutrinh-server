import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { ApiError } from './api/errors'
import { SessionProvider } from './auth/session'
import { AppRoutes } from './routes'
import './theme/global.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xx answers are final; network errors and 5xx are retried
      retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
      staleTime: 10_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/admin">
        <SessionProvider>
          <AppRoutes />
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
