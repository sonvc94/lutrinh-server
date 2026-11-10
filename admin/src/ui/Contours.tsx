/** The contour motif (docs/08 §4): thin Contour ovals, the only ornament; never a fill. */
export function Contours({
  width = '100%',
  height = '100%',
  rings = 5,
  className,
}: {
  width?: number | string
  height?: number | string
  rings?: number
  className?: string
}) {
  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox="0 0 200 120"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      {Array.from({ length: rings }, (_, i) => (
        <ellipse
          key={i}
          cx={100}
          cy={60}
          rx={18 + i * 18}
          ry={10 + i * 11}
          fill="none"
          stroke="#C09A68"
          strokeWidth={i === rings - 2 ? 2 : 1}
        />
      ))}
    </svg>
  )
}
