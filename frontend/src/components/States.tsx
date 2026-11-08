import type { ReactNode } from "react";
import { IconAlert, IconInfo } from "./icons";

interface StateProps {
  title: string;
  text?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ title, text, action, icon }: StateProps) {
  return (
    <div className="state" role="status">
      <div className="state-icon">{icon ?? <IconInfo />}</div>
      <div className="state-title">{title}</div>
      {text && <div className="state-text">{text}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", text, action }: Partial<StateProps>) {
  return (
    <div className="state state-error" role="alert">
      <div className="state-icon">
        <IconAlert />
      </div>
      <div className="state-title">{title}</div>
      {text && <div className="state-text">{text}</div>}
      {action}
    </div>
  );
}

type CalloutTone = "info" | "warning" | "critical";

export function Callout({ tone = "info", title, children }: { tone?: CalloutTone; title?: string; children: ReactNode }) {
  return (
    <div className={`callout callout-${tone}`} role={tone === "critical" ? "alert" : "note"}>
      {tone === "info" ? <IconInfo className="callout-icon" /> : <IconAlert className="callout-icon" />}
      <div className="callout-body">
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
    </div>
  );
}
