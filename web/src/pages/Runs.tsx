import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { controlRun, keys, listRuns } from "@/api/queries";
import { RunTerminal } from "@/components/RunTerminal";
import { Badge, Button, Card, Spinner } from "@/components/ui";

const ACTIVE = new Set(["starting", "running", "stopping"]);

function tone(status: string): "default" | "accent" | "warn" {
  if (status === "running") return "accent";
  if (status === "crashed" || status === "lost") return "warn";
  return "default";
}

export function RunsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: keys.runs, queryFn: listRuns, refetchInterval: 4000 });

  const stop = useMutation({
    mutationFn: (id: string) => controlRun(id, "stop"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.runs }),
  });

  if (isLoading) {
    return <Spinner label="Loading runs" />;
  }
  if (error) {
    return <p className="text-sm text-red-400">{(error as Error).message}</p>;
  }

  const runs = data?.runs ?? [];
  const active = runs.filter((run) => ACTIVE.has(run.status));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Runs</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">Active and recent Flutter sessions across your devices.</p>
      </div>

      {active.length > 0 ? (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-white">Active</h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {active.map((run) => (
              <Card key={run.id} className="overflow-hidden">
                <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
                  <div className="flex items-center gap-2 text-sm">
                    <Link to={`/runs/${encodeURIComponent(run.id)}`} className="text-white hover:underline">
                      {run.project} · {run.device}
                    </Link>
                    <Badge tone={tone(run.status)}>{run.status}</Badge>
                  </div>
                  <div className="flex gap-1">
                    <Link to={`/runs/${encodeURIComponent(run.id)}`} className="text-xs text-[var(--color-accent)] hover:underline">
                      Open
                    </Link>
                    <button className="ml-2 cursor-pointer text-xs text-[var(--color-muted)] hover:text-white" onClick={() => stop.mutate(run.id)}>
                      Stop
                    </button>
                  </div>
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
        <h2 className="mb-2 text-sm font-semibold text-white">History</h2>
        {runs.length === 0 ? (
          <Card className="p-6 text-sm text-[var(--color-muted)]">No runs yet.</Card>
        ) : (
          <Card className="divide-y divide-[var(--color-border)]">
            {runs.map((run) => (
              <div key={run.id} className="flex items-center gap-4 p-3 text-sm">
                <Badge tone={tone(run.status)}>{run.status}</Badge>
                <Link to={`/runs/${encodeURIComponent(run.id)}`} className="min-w-0 flex-1 truncate text-white hover:underline">
                  {run.project} on {run.device}
                </Link>
                <span className="text-xs text-[var(--color-muted)]">{run.mode}</span>
                <span className="text-xs text-[var(--color-muted)]">{run.started_at.replace("T", " ")}</span>
                {ACTIVE.has(run.status) ? (
                  <Button variant="ghost" onClick={() => stop.mutate(run.id)}>
                    Stop
                  </Button>
                ) : null}
              </div>
            ))}
          </Card>
        )}
      </div>
    </div>
  );
}
