import { useState, type ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
  render: () => ReactNode;
}

export function Tabs({ tabs, initial }: { tabs: TabDef[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.id);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b border-[var(--color-border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActive(tab.id)}
            className={`cursor-pointer rounded-t-md px-3 py-2 text-sm transition ${
              tab.id === current?.id
                ? "border-b-2 border-[var(--color-accent)] text-white"
                : "text-[var(--color-muted)] hover:text-white"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div>{current?.render()}</div>
    </div>
  );
}
