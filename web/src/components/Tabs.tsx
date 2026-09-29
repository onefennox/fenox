import { useState, type ReactNode } from "react";

import { cn } from "@/lib/format";

export interface TabDef {
  id: string;
  label: string;
  icon?: ReactNode;
  /** A count or status chip shown beside the label. */
  badge?: ReactNode;
  render: () => ReactNode;
}

/**
 * Tabs with an underline, a badge slot, and a short fade when the panel
 * changes — `key` on the panel so React swaps it rather than reusing the node,
 * which is what makes the animation play at all.
 */
export function Tabs({
  tabs,
  initial,
  active: controlled,
  onChange,
  className = "",
}: {
  tabs: TabDef[];
  initial?: string;
  active?: string;
  onChange?: (id: string) => void;
  className?: string;
}) {
  const [internal, setInternal] = useState(initial ?? tabs[0]?.id);
  const active = controlled ?? internal;
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div className={cn("space-y-4", className)}>
      <div
        className="scrollbar-none -mb-px flex gap-0.5 overflow-x-auto border-b border-[var(--color-border)]"
        role="tablist"
      >
        {tabs.map((tab) => {
          const selected = tab.id === current?.id;
          return (
            <button
              key={tab.id}
              role="tab"
              type="button"
              aria-selected={selected}
              onClick={() => {
                setInternal(tab.id);
                onChange?.(tab.id);
              }}
              className={cn(
                "flex shrink-0 cursor-pointer items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-[var(--duration-fast)]",
                selected
                  ? "border-[var(--color-accent)] text-[var(--color-text)]"
                  : "border-transparent text-[var(--color-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-text)]",
              )}
            >
              {tab.icon}
              {tab.label}
              {tab.badge}
            </button>
          );
        })}
      </div>
      <div key={current?.id} className="animate-in">
        {current?.render()}
      </div>
    </div>
  );
}
