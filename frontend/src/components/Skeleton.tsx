import type { CSSProperties } from "react";

interface SkeletonProps {
  className?: string;
  height?: number | string;
  width?: number | string;
  style?: CSSProperties;
}

export function Skeleton({ className = "", height, width, style }: SkeletonProps) {
  return <div className={`skeleton ${className}`.trim()} style={{ height, width, ...style }} aria-hidden="true" />;
}

export function PageSkeleton({ kpis = 4, charts = 2 }: { kpis?: number; charts?: number }) {
  return (
    <div className="page" aria-busy="true" aria-label="Loading">
      <div className="stack">
        <Skeleton height={14} width={120} />
        <Skeleton height={34} width={420} />
        <Skeleton height={16} width={560} />
      </div>
      <div className="grid grid-kpi">
        {Array.from({ length: kpis }, (_, index) => (
          <Skeleton key={index} height={118} style={{ borderRadius: 12 }} />
        ))}
      </div>
      <div className="grid grid-2">
        {Array.from({ length: charts }, (_, index) => (
          <Skeleton key={index} height={360} style={{ borderRadius: 12 }} />
        ))}
      </div>
    </div>
  );
}
