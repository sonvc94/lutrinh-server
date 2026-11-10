import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { LngLat } from '../../src/draft/model'
import type { MapAdapter } from '../../src/map/MapAdapter'
import { MapAdapterContext, RouteMap } from '../../src/map/RouteMap'

function fakeAdapter() {
  const clicks: ((p: LngLat) => void)[] = []
  const a: MapAdapter = {
    mount: vi.fn(),
    setStops: vi.fn(),
    setLegs: vi.fn(),
    setSketch: vi.fn(),
    setPinsDraggable: vi.fn(),
    fitTo: vi.fn(),
    onMapClick: (cb) => {
      clicks.push(cb)
      return () => clicks.splice(clicks.indexOf(cb), 1)
    },
    onPinClick: () => () => {},
    onPinDrag: () => () => {},
    destroy: vi.fn(),
  }
  return { a, click: (p: LngLat) => clicks.forEach((cb) => cb(p)) }
}

describe('RouteMap', () => {
  it('talks to the editor only through MapAdapter', async () => {
    const { a, click } = fakeAdapter()
    const onMapClick = vi.fn()
    const pins = [
      { id: 's1', at: { lng: 105, lat: 21 }, label: '1', kind: 'start' as const, title: 'A' },
    ]
    const { unmount } = render(
      <MapAdapterContext.Provider value={() => Promise.resolve(a)}>
        <RouteMap
          pins={pins}
          lines={[]}
          selectedId="s1"
          fit={{ key: 'x', bounds: { south: 21, west: 105, north: 21, east: 105 } }}
          onMapClick={onMapClick}
        />
      </MapAdapterContext.Provider>,
    )
    expect(screen.getByTestId('route-map')).toBeInTheDocument()
    await vi.waitFor(() => expect(a.mount).toHaveBeenCalled())
    await vi.waitFor(() => expect(a.setStops).toHaveBeenCalledWith(pins, 's1'))
    expect(a.fitTo).toHaveBeenCalled()
    act(() => click({ lng: 106, lat: 22 }))
    expect(onMapClick).toHaveBeenCalledWith({ lng: 106, lat: 22 })
    unmount()
    expect(a.destroy).toHaveBeenCalled()
  })
})
