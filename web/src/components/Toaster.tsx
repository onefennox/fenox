import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect } from "react";

import { useToasts, type Toast } from "@/lib/toast";
import { cn } from "@/lib/format";

const TONES = {
  info: { icon: Info, className: "text-[var(--color-accent)]" },
  success: { icon: CheckCircle2, className: "text-[var(--color-success)]" },
  error: { icon: AlertTriangle, className: "text-[var(--color-danger)]" },
} as const;

const LIFETIME = 6000;

function ToastRow({ toast }: { toast: Toast }) {
  const dismiss = useToasts((state) => state.dismiss);
  const tone = TONES[toast.tone];
  const Icon = tone.icon;

  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), LIFETIME);
    return () => clearTimeout(timer);
  }, [dismiss, toast.id]);

  return (
    <div
      role="status"
      className="animate-in pointer-events-auto flex w-80 items-start gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-strong)] bg-[var(--color-elevated)] p-3 shadow-xl"
    >
      <Icon size={15} className={cn("mt-0.5 shrink-0", tone.className)} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--color-text)]">{toast.title}</p>
        {toast.description ? (
          <p className="mt-0.5 text-xs break-words text-[var(--color-muted)]">{toast.description}</p>
        ) : null}
      </div>
      <button
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss"
        className="cursor-pointer rounded-[var(--radius-sm)] p-0.5 text-[var(--color-subtle)] transition-colors hover:text-[var(--color-text)]"
      >
        <X size={13} />
      </button>
    </div>
  );
}

export function Toaster() {
  const items = useToasts((state) => state.items);
  if (!items.length) return null;
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex flex-col items-end gap-2">
      {items.map((item) => (
        <ToastRow key={item.id} toast={item} />
      ))}
    </div>
  );
}
