// Lint rules. The map boundary (page 04 §F, like the app's R35): only src/map/maplibre/ may
// import maplibre-gl; everything else talks to the map through src/map/MapAdapter.ts.
import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export const MAP_BOUNDARY = {
  paths: [
    {
      name: 'maplibre-gl',
      message: 'Only src/map/maplibre/ may import maplibre-gl; use the MapAdapter interface.',
    },
  ],
  patterns: [
    {
      group: ['maplibre-gl/*'],
      message: 'Only src/map/maplibre/ may import maplibre-gl; use the MapAdapter interface.',
    },
  ],
}

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'test-results', 'playwright-report', 'src/api/schema.d.ts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/set-state-in-effect': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-restricted-imports': ['error', MAP_BOUNDARY],
    },
  },
  {
    files: ['src/map/maplibre/**/*.{ts,tsx}'],
    rules: { 'no-restricted-imports': 'off' },
  },
)
