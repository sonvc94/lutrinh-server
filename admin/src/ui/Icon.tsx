/** Line icons (24-unit grid, 1.8 stroke), drawn here so the admin needs no icon package. */
const PATHS: Record<string, string> = {
  pin: 'M12 21s-6-5.3-6-10a6 6 0 1 1 12 0c0 4.7-6 10-6 10Zm0-8a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z',
  pencil: 'M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4',
  fit: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
  search: 'M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14Zm5-2 4 4',
  plus: 'M12 5v14M5 12h14',
  file: 'M7 3h7l4 4v14H7V3Zm7 0v4h4',
  back: 'M15 5l-7 7 7 7',
  more: 'M12 6h.01M12 12h.01M12 18h.01',
  grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01',
  check: 'M5 12l5 5 9-10',
  cross: 'M6 6l12 12M18 6 6 18',
  clock: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Zm0-13v4l3 2',
  upload: 'M12 16V4m0 0-4 4m4-4 4 4M5 20h14',
  undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  image: 'M4 5h16v14H4V5Zm0 11 5-5 4 4 2-2 5 5M15 9h.01',
  video: 'M4 6h11v12H4V6Zm11 4 5-3v10l-5-3',
  bike: 'M5 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm14 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM5 14l4-6h5l5 6M9 8l3 6h2',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
}

export function Icon({
  name,
  size = 18,
  title,
}: {
  name: keyof typeof PATHS | string
  size?: number
  title?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={name === 'more' || name === 'grip' ? 3 : 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      <path d={PATHS[name] ?? ''} />
    </svg>
  )
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#1F2A24" />
      <path
        d="M7 24c4-1 5-6 9-8s6-6 9-9"
        stroke="#fff"
        strokeWidth="5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M7 24c4-1 5-6 9-8s6-6 9-9"
        stroke="#E4572E"
        strokeWidth="2.6"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
}
