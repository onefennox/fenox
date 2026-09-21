import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { controlRun, getRun, keys } from "@/api/queries";
import type { Run } from "@/api/types";
import { RunTerminal } from "@/components/RunTerminal";
import { Badge, Button, Card, Spinner } from "@/components/ui";

const ACTIVE = new Set(["starting", "running", "stopping"]);

function statusTone(status: string): "default" | "accent" | "warn" {
  if (status === "running") return "accent";
  if (status === "crashed" || status === "lost") return "warn";
  return "default";
}

export function RunPage() {
  const { id = "" } = useParams();
  const runId = decodeURIComponent(id);
  const queryClient = useQueryClient();
  const [live, setLive] = useState<Partial<Run>>({});

  const run = useQuery({
    queryKey: keys.run(runId),
    queryFn: () => getRun(runId),
    refetchInterval: (query) => (ACTIVE.has((query.state.data as Run | undefined)?.status ?? "") ? 5000 : false),
  });

  const control = useMutation({
    mutationFn: (action: "reload" | "restart" | "stop") => controlRun(runId, action),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.run(runId) });
      queryClient.invalidateQueries({ queryKey: keys.runs });
    },
  });

  const onStatus = useCallback((message: Partial<Run> & { type?: string }) => {
    const { type, ...rest } = message;
    if (type === "status" || type === "exit") {
      setLive((previous) => ({ ...previous, ...rest }));
    }
  }, []);

  if (run.isLoading) {
    return <Spinner label="Loading run" />;
  }
  if (run.error || !run.data) {
    return <p className="text-sm text-red-400">{(run.error as Error | null)?.message ?? "Run not found."}</p>;
  }

  const merged = { ...run.data, ...live } as Run;
  const active = ACTIVE.has(merged.status);

  return (
    <div className="space-y-5">
      <div>
        <Link to="/runs" className="text-xs text-[var(--color-muted)] hover:text-white">
          &larr; Runs
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold text-white">
            {merged.project} <span className="text-[var(--color-muted)]">on</span> {merged.device}
          </h1>
          <Badge tone={statusTone(merged.status)}>{merged.status}</Badge>
          <Badge>{merged.mode}</Badge>
          {merged.devtools ? (
            <a href={merged.devtools} target="_blank" rel="noreferrer" className="text-sm text-[var(--color-accent)] hover:underline">
              Open DevTools
            </a>
          ) : null}
        </div>
      </div>

      <div className="flex gap-2">
        <Button onClick={() => control.mutate("reload")} disabled={!active || control.isPending}>
          Reload
        </Button>
        <Button variant="secondary" onClick={() => control.mutate("restart")} disabled={!active || control.isPending}>
          Restart
        </Button>
        <Button variant="danger" onClick={() => control.mutate("stop")} disabled={!active || control.isPending}>
          Stop
        </Button>
      </div>

      {control.error ? <p className="text-sm text-red-400">{(control.error as Error).message}</p> : null}

      <Card className="h-[560px] overflow-hidden p-2">
        <RunTerminal runId={runId} onStatus={onStatus} />
      </Card>
    </div>
  );
}
