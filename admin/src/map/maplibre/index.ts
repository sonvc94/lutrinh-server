import type { MapAdapter } from '../MapAdapter'
import { MapLibreAdapter } from './MapLibreAdapter'

export function createMapLibreAdapter(): MapAdapter {
  return new MapLibreAdapter()
}
