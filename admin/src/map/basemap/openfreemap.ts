/** OpenFreeMap basemap, the same source as the app (R35, docs/05): style URL and credit line. */
export const OPENFREEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron'
export const OPENFREEMAP_CREDIT =
  '<a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'

/** Topo-outdoor recolouring of the basemap (docs/08 §2 Map): paper, woods, water. */
export const TOPO_PAINT = {
  background: '#EFEBDA',
  water: '#BFDDE6',
  vegetation: '#D8E4C4',
  residential: '#E8E3CE',
  building: '#E3DEC8',
  label: '#5A5948',
  halo: '#FBFAF2',
} as const

export const VIETNAM_CENTER = { lng: 105.85, lat: 21.03 }
