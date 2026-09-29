import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";
import { useEffect, useId } from "react";

import { cn } from "@/lib/format";

/* ------------------------------------------------------------------ button */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
type ButtonSize = "sm" | "md" | "icon";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] disabled:opacity-50 shadow-[0_1px_2px_rgba(0,0,0,0.25)]",
  secondary:
    "bg-[var(--color-elevated)] text-[var(--color-text)] border border-[var(--color-border)] hover:border-[var(--color-border-strong)] hover:bg-[var(--color-panel-hover)] disabled:opacity-50",
  ghost:
    "text-[var(--color-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-panel-hover)] disabled:opacity-40",
  danger: "bg-[var(--color-danger)]/90 text-white hover:bg-[var(--color-danger)] disabled:opacity-50",
  success: "bg-[var(--color-success)]/90 text-white hover:bg-[var(--color-success)] disabled:opacity-50",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  icon: "h-8 w-8 justify-center",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex cursor-pointer items-center rounded-[var(--radius-md)] font-medium whitespace-nowrap",
        "transition-colors duration-[var(--duration-fast)] disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
    />
  );
}

/* ------------------------------------------------------------------- input */

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm",
        "text-[var(--color-text)] outline-none transition-colors duration-[var(--duration-fast)]",
        "placeholder:text-[var(--color-subtle)] focus:border-[var(--color-accent)] disabled:opacity-50",
        className,
      )}
    />
  );
}

export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        "h-9 cursor-pointer rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-sm",
        "text-[var(--color-text)] outline-none transition-colors focus:border-[var(--color-accent)]",
        className,
      )}
    >
      {children}
    </select>
  );
}

export function Textarea({ className = "", ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(
        "w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm",
        "font-mono text-[var(--color-text)] outline-none transition-colors",
        "placeholder:text-[var(--color-subtle)] focus:border-[var(--color-accent)]",
        className,
      )}
    />
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-[11px] font-medium tracking-wide text-[var(--color-muted)] uppercase">{label}</span>
      {children}
      {error ? (
        <span className="block text-xs text-[var(--color-danger)]">{error}</span>
      ) : hint ? (
        <span className="block text-xs text-[var(--color-subtle)]">{hint}</span>
      ) : null}
    </label>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors",
        checked ? "bg-[var(--color-accent)]" : "bg-[var(--color-border-strong)]",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-[var(--duration-fast)]",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: Array<{ id: T; label: string; icon?: ReactNode; title?: string }>;
  onChange: (next: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="tablist"
      className="inline-flex items-center gap-0.5 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5"
    >
      {options.map((option) => {
        const active = option.id === value;
        return (
          <button
            key={option.id}
            role="tab"
            type="button"
            aria-selected={active}
            title={option.title}
            onClick={() => onChange(option.id)}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius-sm)] font-medium transition-colors",
              size === "sm" ? "h-6 px-2 text-xs" : "h-7 px-2.5 text-xs",
              active
                ? "bg-[var(--color-elevated)] text-[var(--color-text)] shadow-[0_1px_2px_rgba(0,0,0,0.2)]"
                : "text-[var(--color-muted)] hover:text-[var(--color-text)]",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------- card */

export function Card({
  className = "",
  interactive = false,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      {...props}
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-panel)]",
        interactive &&
          "transition-colors duration-[var(--duration-fast)] hover:border-[var(--color-border-strong)] hover:bg-[var(--color-panel-hover)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A titled section inside a card, with an optional action on the right. */
export function Section({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--color-text)]">{title}</h2>
          {description ? <p className="mt-0.5 text-xs text-[var(--color-muted)]">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </Card>
  );
}

/* ------------------------------------------------------------------- badge */

type BadgeTone = "default" | "accent" | "success" | "warn" | "danger";

export function Badge({
  children,
  tone = "default",
  className = "",
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}) {
  const tones: Record<BadgeTone, string> = {
    default: "border-[var(--color-border-strong)] text-[var(--color-muted)]",
    accent: "border-[var(--color-accent)]/40 text-[var(--color-accent)] bg-[var(--color-accent-soft)]",
    success: "border-[var(--color-success)]/40 text-[var(--color-success)] bg-[var(--color-success)]/10",
    warn: "border-[var(--color-warning)]/40 text-[var(--color-warning)] bg-[var(--color-warning)]/10",
    danger: "border-[var(--color-danger)]/40 text-[var(--color-danger)] bg-[var(--color-danger)]/10",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ online, disabled }: { online: boolean; disabled?: boolean }) {
  const color = disabled ? "bg-[var(--color-subtle)]" : online ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]";
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0" aria-hidden>
      <span className={cn("inline-block h-2 w-2 rounded-full", color)} />
    </span>
  );
}

/* --------------------------------------------------------------- feedback */

export function Spinner({ label, className = "" }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5 text-sm text-[var(--color-muted)]", className)}>
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--color-border-strong)] border-t-[var(--color-accent)]" />
      {label}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={cn("animate-pulse-soft rounded-[var(--radius-sm)] bg-[var(--color-border)]", className)} />;
}

/** A skeleton block for list rows, so loading looks like the content will. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-3">
          <Skeleton className="h-8 w-8 rounded-full" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="rounded-[var(--radius-md)] border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 px-3 py-2 text-sm text-[var(--color-danger)]">
      {children}
    </p>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className = "",
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {icon ? <div className="mb-3 text-[var(--color-subtle)]">{icon}</div> : null}
      <p className="text-sm font-medium text-[var(--color-text)]">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-xs text-[var(--color-muted)]">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/* ----------------------------------------------------------------- tooltip */

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group/tt relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 scale-95 rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] bg-[var(--color-elevated)] px-2 py-1 text-[11px] whitespace-nowrap text-[var(--color-text)] opacity-0 shadow-lg transition-all duration-[var(--duration-fast)] group-hover/tt:scale-100 group-hover/tt:opacity-100"
      >
        {label}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------- modal */

export function Modal({
  title,
  description,
  onClose,
  children,
  footer,
  size = "md",
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const titleId = useId();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const widths = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-2xl",
    xl: "max-w-4xl",
  } as const;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-[2px]"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "animate-in flex max-h-[85vh] w-full flex-col rounded-[var(--radius-xl)] border border-[var(--color-border)] bg-[var(--color-panel)] shadow-2xl",
          widths[size],
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--color-border)] px-4 py-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-semibold text-[var(--color-text)]">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-xs text-[var(--color-muted)]">{description}</p> : null}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="cursor-pointer rounded-[var(--radius-sm)] p-1 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 2l10 10M12 2L2 12" />
            </svg>
          </button>
        </header>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
        {footer ? (
          <footer className="flex shrink-0 justify-end gap-2 border-t border-[var(--color-border)] px-4 py-3">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  );
}
