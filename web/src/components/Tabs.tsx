import { useState, type ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
  icon?: ReactNode;
  render: () => ReactNode;
}

export function Tabs({ tabs, initial }: { tabs: TabDef[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.id);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div className="space-y-5">
      <div className="scrollbar-none flex gap-1 overflow-x-auto border-b border-[var(--color-border)]" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActive(tab.id)}
            role="tab"
            aria-selected={tab.id === current?.id}
            className={`flex shrink-0 cursor-pointer items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition ${
              tab.id === current?.id
                ? "border-[var(--color-accent)] text-white"
                : "border-transparent text-[var(--color-muted)] hover:border-[var(--color-border)] hover:text-white"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>
      <div>{current?.render()}</div>
    </div>
  );
}
