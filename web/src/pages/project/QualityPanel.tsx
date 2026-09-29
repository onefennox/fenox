import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";

import { getQualityActions, runQuality } from "@/api/queries";
import type { QualityResult } from "@/api/types";
import { Button, Card, EmptyState, SkeletonRows } from "@/components/ui";
import { cn } from "@/lib/format";

/**
 * The checks a developer runs constantly: does it analyze clean, do the tests
 * pass, are the packages current, can this machine build it at all.
 *
 * Output is shown verbatim rather than summarised — the useful part of `flutter
 * analyze` is the list, not a count — and each run is kept on screen so a
 * failing check can be read without re-running it.
 */
export function QualityPanel({ project }: { project: string }) {
  const actions = useQuery({
    queryKey: ["quality-actions", project],
    queryFn: () => getQualityActions(project),
  });

  const [results, setResults] = useState<Record<string, QualityResult>>({});
  const [pending, setPending] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: (action: string) => runQuality(project, action),
    onMutate: (action) => setPending(action),
    onSuccess: (result) => setResults((current) => ({ ...current, [result.action]: result })),
    onSettled: () => setPending(null),
  });

  const running = pending;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-semibold">Checks</h2>
        <p className="mt-0.5 mb-3 text-xs text-[var(--color-muted)]">
          Run against the project directory. Each check keeps its output below.
        </p>
        {actions.isLoading ? (
          <SkeletonRows rows={2} />
        ) : (
          <div className="flex flex-wrap gap-2">
            {(actions.data?.actions ?? []).map((action) => {
              const result = results[action.id];
              return (
                <button
                  key={action.id}
                  type="button"
                  disabled={Boolean(running)}
                  onClick={() => run.mutate(action.id)}
                  title={action.hint}
                  className={cn(
                    "flex cursor-pointer flex-col items-start rounded-[var(--radius-md)] border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    result
                      ? result.ok
                        ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/5"
                        : "border-[var(--color-danger)]/40 bg-[var(--color-danger)]/5"
                      : "border-[var(--color-border)] bg-[var(--color-elevated)] hover:border-[var(--color-accent)]/50",
                  )}
                >
                  <span className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-text)]">
                    {running === action.id ? <Loader2 size={12} className="animate-spin" /> : null}
                    {action.label}
                  </span>
                  <span className="mt-0.5 text-[10px] text-[var(--color-subtle)]">
                    {result ? `${result.seconds}s` : action.hint}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        {run.error ? <p className="mt-3 text-sm text-[var(--color-danger)]">{(run.error as Error).message}</p> : null}
      </Card>

      {Object.keys(results).length === 0 ? (
        <Card>
          <EmptyState
            icon={<ShieldCheck size={20} />}
            title="No checks run yet"
            description="Analyze and Test are the two worth wiring into your habit — they catch most problems before a build does."
          />
        </Card>
      ) : (
        Object.values(results).map((result) => (
          <Card key={result.action} className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
              <span className="flex items-center gap-2 text-xs font-medium">
                {result.ok ? (
                  <CheckCircle2 size={13} className="text-[var(--color-success)]" />
                ) : (
                  <XCircle size={13} className="text-[var(--color-danger)]" />
                )}
                {result.action}
              </span>
              <span className="tnum text-[11px] text-[var(--color-subtle)]">{result.seconds}s</span>
            </div>
            <pre className="scroll-thin max-h-72 overflow-auto bg-[var(--color-surface)] p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--color-muted)]">
              {result.output}
            </pre>
          </Card>
        ))
      )}

      {Object.keys(results).length > 0 ? (
        <Button variant="ghost" size="sm" onClick={() => setResults({})}>
          Clear results
        </Button>
      ) : null}
    </div>
  );
}
