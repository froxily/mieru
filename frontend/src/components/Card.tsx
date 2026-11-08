import { useState, type CSSProperties, type ReactNode } from "react";
import { IconChart, IconTable } from "./icons";

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  stagger?: number;
  interactive?: boolean;
}

export function Card({ title, subtitle, actions, footer, children, className = "", stagger = 0, interactive = false }: CardProps) {
  return (
    <section className={`card${interactive ? " card-interactive" : ""} ${className}`.trim()} style={{ "--stagger": stagger } as CSSProperties}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
      {footer && <footer className="card-footer">{footer}</footer>}
    </section>
  );
}

interface ChartCardProps extends Omit<CardProps, "children" | "actions"> {
  chart: ReactNode;
  table: ReactNode;
  extraActions?: ReactNode;
}

export function ChartCard({ chart, table, extraActions, ...cardProps }: ChartCardProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <Card
      {...cardProps}
      actions={
        <>
          {extraActions}
          <div className="segmented" role="group" aria-label="Chart or table view">
            <button type="button" aria-pressed={view === "chart"} onClick={() => setView("chart")} title="Chart view" aria-label="Chart view">
              <IconChart width={14} height={14} />
            </button>
            <button type="button" aria-pressed={view === "table"} onClick={() => setView("table")} title="Table view" aria-label="Table view">
              <IconTable width={14} height={14} />
            </button>
          </div>
        </>
      }
    >
      {view === "chart" ? chart : table}
    </Card>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
