import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const buttonStyles: Record<ButtonVariant, string> = {
  primary: "bg-[var(--color-accent)] text-white hover:brightness-110 disabled:opacity-50",
  secondary: "bg-[var(--color-panel-hover)] text-white hover:bg-[var(--color-border)] disabled:opacity-50",
  ghost: "text-[var(--color-muted)] hover:text-white hover:bg-[var(--color-panel-hover)]",
  danger: "bg-red-600/90 text-white hover:bg-red-600 disabled:opacity-50",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      {...props}
      className={`inline-flex cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed ${buttonStyles[variant]} ${className}`}
    />
  );
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-white outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-accent)] ${className}`}
    />
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium tracking-wide text-[var(--color-muted)] uppercase">{label}</span>
      {children}
    </label>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] ${className}`}>
      {children}
    </div>
  );
}

export function StatusDot({ online, disabled }: { online: boolean; disabled?: boolean }) {
  const color = disabled ? "bg-[var(--color-muted)]" : online ? "bg-emerald-500" : "bg-red-500";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} aria-hidden />;
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "accent" | "warn" }) {
  const tones = {
    default: "border-[var(--color-border)] text-[var(--color-muted)]",
    accent: "border-[var(--color-accent)]/40 text-[var(--color-accent)]",
    warn: "border-amber-500/40 text-amber-400",
  } as const;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${tones[tone]}`}>{children}</span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-[var(--color-muted)]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-accent)]" />
      {label}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Wider panel for content that needs the room, such as the folder picker. */
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div
        className={`flex max-h-[85vh] w-full flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-5 ${
          wide ? "max-w-3xl" : "max-w-md"
        }`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex shrink-0 items-center justify-between">
          <h2 className="text-base font-semibold text-white">{title}</h2>
          <button className="cursor-pointer text-[var(--color-muted)] hover:text-white" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) {
    return null;
  }
  return <p className="text-sm text-red-400">{children}</p>;
}
