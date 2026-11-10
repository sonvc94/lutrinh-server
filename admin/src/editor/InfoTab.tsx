/** Page 04 B "Thông tin": title, description, days, credits (limits from the schema). */
import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { LIMITS } from '../draft/limits'
import { Field, ui } from '../ui/ui'
import { useEditor } from './context'
import css from './InfoTab.module.css'

export const infoSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, 'Lộ trình cần có tên.')
    .max(LIMITS.routeTitle, `Tối đa ${LIMITS.routeTitle} ký tự.`),
  description: z.string().max(LIMITS.routeDescription, `Tối đa ${LIMITS.routeDescription} ký tự.`),
  days: z.coerce.number().int().min(1).max(LIMITS.daysMax, `Tối đa ${LIMITS.daysMax} ngày.`),
  credits: z.string(),
})
type In = z.input<typeof infoSchema>
type Out = z.output<typeof infoSchema>

export function InfoTab() {
  const { saver, state } = useEditor()
  const b = state.body
  const lastDay = b.stops.reduce((m, s) => Math.max(m, s.day), 1)
  const toForm = (): In => ({
    title: b.title,
    description: b.description,
    days: b.days,
    credits: b.credits.join('\n'),
  })
  const { register, subscribe, reset, getValues, formState } = useForm<In, unknown, Out>({
    resolver: zodResolver(infoSchema),
    mode: 'onChange',
    defaultValues: toForm(),
  })

  useEffect(() => {
    return subscribe({
      formState: { values: true },
      callback: ({ values }) => {
        const ok = infoSchema.safeParse(values)
        if (!ok.success) return
        const d = ok.data
        saver.edit(
          (body) => ({
            ...body,
            title: d.title,
            description: d.description,
            days: Math.max(d.days, lastDay),
            credits: d.credits
              .split('\n')
              .map((c) => c.trim())
              .filter(Boolean),
          }),
          false,
        )
      },
    })
  }, [subscribe, saver, lastDay])

  const formKey = JSON.stringify([b.title, b.description, b.days, b.credits])
  useEffect(() => {
    const cur = getValues()
    const now = JSON.parse(formKey) as [string, string, number, string[]]
    const same =
      cur.title.trim() === now[0] &&
      cur.description === now[1] &&
      Number(cur.days) === now[2] &&
      cur.credits
        .split('\n')
        .map((c) => c.trim())
        .filter(Boolean)
        .join('\n') === now[3].join('\n')
    if (!same)
      reset({ title: now[0], description: now[1], days: now[2], credits: now[3].join('\n') })
  }, [formKey, getValues, reset])

  const e = formState.errors
  return (
    <div className={css.page}>
      <form
        className={ui.panel}
        onSubmit={(ev) => ev.preventDefault()}
        aria-label="Thông tin lộ trình"
      >
        <div className={css.grid}>
          <Field
            label="Tên lộ trình"
            htmlFor="info-title"
            error={e.title?.message}
            hint={`Tối đa ${LIMITS.routeTitle} ký tự`}
          >
            <input
              id="info-title"
              className={ui.input}
              aria-invalid={!!e.title}
              {...register('title')}
            />
          </Field>
          <Field
            label="Số ngày"
            htmlFor="info-days"
            error={e.days?.message}
            hint={lastDay > 1 ? `Không ít hơn ${lastDay} (ngày của điểm cuối)` : undefined}
          >
            <input
              id="info-days"
              type="number"
              min={lastDay}
              max={LIMITS.daysMax}
              className={ui.input}
              aria-invalid={!!e.days}
              {...register('days')}
            />
          </Field>
        </div>
        <Field label="Mô tả" htmlFor="info-description" error={e.description?.message}>
          <textarea
            id="info-description"
            rows={6}
            className={ui.input}
            {...register('description')}
          />
        </Field>
        <Field
          label="Nguồn, ghi công"
          htmlFor="info-credits"
          hint="Mỗi dòng một nguồn; hiện ở cuối lộ trình trong app."
        >
          <textarea id="info-credits" rows={3} className={ui.input} {...register('credits')} />
        </Field>
      </form>
    </div>
  )
}
