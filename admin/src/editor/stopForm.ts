import { z } from 'zod'
import { ARRIVALS, LIMITS } from '../draft/limits'

/** The stop form (page 04 B, selected row): limits from spec/route.schema.json. */
export const stopSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, 'Điểm cần có tên.')
    .max(LIMITS.stopTitle, `Tối đa ${LIMITS.stopTitle} ký tự.`),
  time: z
    .string()
    .refine((t) => t === '' || LIMITS.timePattern.test(t), 'Giờ dạng HH:MM, ví dụ 07:30.'),
  day: z.coerce
    .number()
    .int()
    .min(1, 'Ngày từ 1.')
    .max(LIMITS.daysMax, `Tối đa ${LIMITS.daysMax} ngày.`),
  arrival: z.enum(['', ...ARRIVALS]),
  note: z.string().max(LIMITS.stopNote, `Tối đa ${LIMITS.stopNote} ký tự.`),
  arrivalNote: z.string().trim().max(LIMITS.arrivalNote, `Tối đa ${LIMITS.arrivalNote} ký tự.`),
})

export type StopFormIn = z.input<typeof stopSchema>
export type StopFormOut = z.output<typeof stopSchema>
