import type { ButtonHTMLAttributes, ReactNode } from 'react'
import css from './ui.module.css'

type Variant = 'default' | 'primary' | 'quiet' | 'danger'

export function Button({
  variant = 'default',
  small,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  const cls = [css.button, variant !== 'default' && css[variant], small && css.small, className]
  return <button type="button" {...rest} className={cls.filter(Boolean).join(' ')} />
}

export type Tone = 'easy' | 'moderate' | 'hard' | 'neutral' | 'dark'

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`${css.badge} ${css[tone]}`}>{children}</span>
}

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string
  hint?: ReactNode
  error?: string | undefined
  htmlFor?: string
  children: ReactNode
}) {
  return (
    <div className={css.field}>
      <label className={css.label} htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <span className={css.error} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className={css.hint}>{hint}</span>
      ) : null}
    </div>
  )
}

export const ui = css
