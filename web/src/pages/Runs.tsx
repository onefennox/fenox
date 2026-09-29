import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { Link } from "react-router-dom";

import { controlRun, keys, listRuns } from "@/api/queries";
import { RunTerminal } from "@/components/RunTerminal";
import { Badge, Button, Card, EmptyState, SkeletonRows } from "@/components/ui";
import { timeAgo } from "@/lib/format";

const ACTIVE = new Set(["starting", "running", "stopping"]);

function tone(status: string): "default" | "accent" | "warn" | "success" | "danger" {
  if (status === "running" || status === "starting") return "accent";
  if (status === "finished") return "success";
  if (status === "crashed" || status === "lost") return "danger";
  if (status === "stopping") return "warn";
  return "default";
}

export function RunsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.runs, queryFn: listRuns, refetchInterval: 4000 });

  const stop = useMutation({
    mutationFn: (id: string) => controlRun(id, "stop"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.runs }),
  });

  if (error) {
    return <p className="text-sm text-[var(--color-danger)]">{(error as Error).message}</p>;
  }

  const runs = data?.runs ?? [];
  const active = runs.filter((run) => ACTIVE.has(run.status));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Runs</h1>
        <p className="mt-0.5 text-sm text-[var(--color-muted)]">
          Flutter sessions, live and finished. Each one is a real <span className="font-mono">flutter run</span>.
        </p>
      </div>

      {isLoading ? (
        <Card className="p-4">
          <SkeletonRows rows={4} />
        </Card>
      ) : runs.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Play size={22} />}
            title="No runs yet"
            description="Open a project and press Run — the session appears here with a live terminal."
            action={
              <Link to="/projects">
                <Button size="sm">Go to projects</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          {active.length > 0 ? (
            <div>
              <h2 className="mb-2 text-xs font-semibold tracking-wider text-[var(--color-subtle)] uppercase">
                Active · {active.length}
              </h2>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {active.map((run) => (
                  <Card key={run.id} className="overflow-hidden">
                    <div className="flex items-center justify-between gap-2 border-b border-[var(--color-border)] px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Link
                          to={`/runs/${encodeURIComponent(run.id)}`}
                          className="truncate text-sm font-medium hover:underline"
                        >
                          {run.project} · {run.device}
                        </Link>
                        <Badge tone={tone(run.status)}>{run.status}</Badge>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="shrink-0"
                        onClick={() => stop.mutate(run.id)}
                        disabled={stop.isPending}
                      >
                        <Square size={12} />
                        Stop
                      </Button>
                    </div>
                    <div className="h-56">
                      <RunTerminal runId={run.id} />
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <h2 className="mb-2 text-xs font-semibold tracking-wider text-[var(--color-subtle)] uppercase">History</h2>
            <Card className="overflow-hidden">
              <div className="grid grid-cols-[92px_minmax(0,1fr)_70px_88px] gap-3 border-b border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase">
                <span>Status</span>
                <span>Run</span>
                <span>Mode</span>
                <span className="text-right">When</span>
              </div>
              <div className="divide-y divide-[var(--color-border)]">
                {runs.map((run) => (
                  <Link
                    key={run.id}
                    to={`/runs/${encodeURIComponent(run.id)}`}
                    className="grid grid-cols-[92px_minmax(0,1fr)_70px_88px] items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-[var(--color-panel-hover)]"
                  >
                    <Badge tone={tone(run.status)}>{run.status}</Badge>
                    <span className="truncate">
                      {run.project} <span className="text-[var(--color-subtle)]">on</span> {run.device}
                    </span>
                    <span className="truncate text-xs text-[var(--color-muted)]">{run.mode}</span>
                    <span className="tnum text-right text-xs text-[var(--color-subtle)]">{timeAgo(run.started_at)}</span>
                  </Link>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
