import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { api, unwrap } from '../api/client'
import { errorText } from '../api/errors'
import { Button, Field, ui } from '../ui/ui'
import { Contours } from '../ui/Contours'
import { Logo } from '../ui/Icon'
import css from './LoginPage.module.css'
import { makeLoginSchema, safeNext } from './login'
import type { LoginForm } from './login'
import { useSession } from './session'

export function LoginPage() {
  const { state, login } = useSession()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const next = safeNext(params.get('next'))
  // What the form asks for: the code field only while the server wants a TOTP. If the answer
  // cannot be read, ask for it (the server then decides).
  const options = useQuery({
    queryKey: ['login-options'],
    queryFn: () => unwrap(api.GET('/admin/api/v1/session/options')),
    retry: false,
    staleTime: 0,
  })
  const totpRequired = options.data?.totpRequired ?? options.isError
  const schema = useMemo(() => makeLoginSchema(totpRequired), [totpRequired])
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({
    resolver: zodResolver(schema),
    defaultValues: { username: '', password: '', code: '' },
  })

  if (state === 'in') return <Navigate to={next} replace />

  const onSubmit = handleSubmit(async (v) => {
    setError(null)
    try {
      await login(v.username, v.password, totpRequired ? v.code : '')
      navigate(next, { replace: true })
    } catch (e) {
      setError(errorText(e))
    }
  })

  return (
    <main className={css.page}>
      <Contours className={css.contours} rings={9} />
      <form className={css.card} onSubmit={onSubmit} noValidate>
        <div className={css.brand}>
          <Logo size={32} />
          <span className="eyebrow">Lữ Trình · quản trị</span>
        </div>
        <h1 className={css.title}>Đăng nhập</h1>
        <Field label="Tên đăng nhập" htmlFor="username" error={errors.username?.message}>
          <input
            id="username"
            autoComplete="username"
            className={ui.input}
            aria-invalid={!!errors.username}
            {...register('username')}
          />
        </Field>
        <Field label="Mật khẩu" htmlFor="password" error={errors.password?.message}>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className={ui.input}
            aria-invalid={!!errors.password}
            {...register('password')}
          />
        </Field>
        {totpRequired && (
          <Field
            label="Mã 6 số từ ứng dụng xác thực"
            htmlFor="code"
            hint="Hoặc gõ một mã dự phòng (10 ký tự)"
            error={errors.code?.message}
          >
            <input
              id="code"
              autoComplete="one-time-code"
              inputMode="text"
              className={`${ui.input} num ${css.code}`}
              aria-invalid={!!errors.code}
              {...register('code')}
            />
          </Field>
        )}
        {error && (
          <div className={ui.notice} role="alert">
            {error}
          </div>
        )}
        <Button type="submit" variant="primary" disabled={isSubmitting || options.isPending}>
          {isSubmitting ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </Button>
      </form>
    </main>
  )
}
