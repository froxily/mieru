import type { CSSProperties } from "react";

const JP_FONT = "'Noto Sans JP', 'Hiragino Sans', 'Yu Gothic', 'Meiryo', sans-serif";

/** Blue rounded square with the white 見 glyph, rendered from a real font so the strokes stay accurate. */
export function MieruMark({ size = 56, className, style }: { size?: number | string; className?: string; style?: CSSProperties }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="MIERU">
      <rect className="mieru-mark__bg" width="64" height="64" rx="15" fill="#2A78D6" />
      <text
        className="mieru-mark__glyph"
        x="32"
        y="33.5"
        textAnchor="middle"
        dominantBaseline="central"
        fill="#FFFFFF"
        fontFamily={JP_FONT}
        fontWeight={700}
        fontSize="36"
      >
        見
      </text>
    </svg>
  );
}
