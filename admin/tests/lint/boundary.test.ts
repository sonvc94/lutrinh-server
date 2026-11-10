// @vitest-environment node
/**
 * The map boundary (page 04 §F): maplibre-gl may only be imported in src/map/maplibre/. Lints a
 * fixture text as if it lived in a file elsewhere, and the same text inside the adapter folder.
 */
import { ESLint } from 'eslint'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const cwd = fileURLToPath(new URL('../..', import.meta.url))
const FIXTURE =
  "import maplibregl from 'maplibre-gl'\nimport 'maplibre-gl/dist/maplibre-gl.css'\nexport const m = maplibregl\n"

async function lint(filePath: string) {
  const eslint = new ESLint({ cwd })
  const [res] = await eslint.lintText(FIXTURE, { filePath })
  return (res?.messages ?? []).filter((m) => m.ruleId === 'no-restricted-imports')
}

describe('ESLint map boundary', () => {
  it('fails maplibre-gl imported outside src/map/maplibre/', async () => {
    const errors = await lint('src/editor/UsesMapLibre.ts')
    expect(errors).toHaveLength(2)
    expect(errors.every((m) => m.severity === 2)).toBe(true)
    expect(errors[0]?.message).toMatch(/src\/map\/maplibre/)
  }, 30_000)

  it('allows it inside src/map/maplibre/', async () => {
    expect(await lint('src/map/maplibre/Other.ts')).toEqual([])
  }, 30_000)
})
