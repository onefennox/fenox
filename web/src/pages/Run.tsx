import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ExternalLink, RefreshCw, RotateCw, Square } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { controlRun, getRun, keys } from "@/api/queries";
import type { Run } from "@/api/types";
import { RunTerminal } from "@/components/RunTerminal";
import { Badge, Button, Card, Skeleton, Tooltip } from "@/components/ui";
import { timeAgo } from "@/lib/format";
import { toast } from "@/lib/toast";

const ACTIVE = new Set(["starting", "running", "stopping"]);

function statusTone(status: string): "default" | "accent" | "warn" | "success" | "danger" {
  if (status === "running" || status === "starting") return "accent";
  if (status === "finished") return "success";
  if (status === "crashed" || status === "lost") return "danger";
  if (status === "stopping") return "warn";
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
    onSuccess: (_result, action) => {
      toast.info(action === "stop" ? "Stopping…" : `${action === "reload" ? "Hot reload" : "Hot restart"} sent`);
      queryClient.invalidateQueries({ queryKey: keys.run(runId) });
      queryClient.invalidateQueries({ queryKey: keys.runs });
    },
    onError: (error: Error) => toast.error("That did not work", error.message),
  });

  const onStatus = useCallback((message: Partial<Run> & { type?: string }) => {
    const { type, ...rest } = message;
    if (type === "status" || type === "exit") {
      setLive((previous) => ({ ...previous, ...rest }));
    }
  }, []);

  if (run.isLoading) {
    return (
      <Card className="space-y-3 p-4">
        <Skeleton className="h-4 w-52" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-[520px] w-full" />
      </Card>
    );
  }
  if (run.error || !run.data) {
    return <p className="text-sm text-[var(--color-danger)]">{(run.error as Error | null)?.message ?? "Run not found."}</p>;
  }

  const merged = { ...run.data, ...live } as Run;
  const active = ACTIVE.has(merged.status);

  return (
    <div className="space-y-3">
      <div>
        <Link
          to="/runs"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]"
        >
          <ChevronLeft size={13} />
          Runs
        </Link>
        <div className="mt-1.5 flex flex-wrap items-center gap-2.5">
          <h1 className="text-lg font-semibold tracking-tight">
            {merged.project} <span className="font-normal text-[var(--color-muted)]">on</span> {merged.device}
          </h1>
          <Badge tone={statusTone(merged.status)}>{merged.status}</Badge>
          <Badge>{merged.mode}</Badge>
          <span className="tnum text-xs text-[var(--color-subtle)]">started {timeAgo(merged.started_at)}</span>
          {merged.devtools ? (
            <a
              href={merged.devtools}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
            >
              <ExternalLink size={12} />
              DevTools
            </a>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {/* Reload and restart are Flutter's own SIGUSR1/SIGUSR2 to the run's pid,
            not a keystroke into a terminal. */}
        <Tooltip label="Hot reload — sends SIGUSR1">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => control.mutate("reload")}
            disabled={!active || control.isPending}
          >
            <RefreshCw size={13} />
            Reload
          </Button>
        </Tooltip>
        <Tooltip label="Hot restart — sends SIGUSR2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => control.mutate("restart")}
            disabled={!active || control.isPending}
          >
            <RotateCw size={13} />
            Restart
          </Button>
        </Tooltip>
        <Button size="sm" variant="danger" onClick={() => control.mutate("stop")} disabled={!active || control.isPending}>
          <Square size={13} />
          Stop
        </Button>
        {!active ? (
          <span className="text-xs text-[var(--color-subtle)]">
            This run has ended, so reload and restart are unavailable.
          </span>
        ) : null}
      </div>

      <Card className="h-[calc(100vh-14rem)] min-h-[420px] overflow-hidden p-1.5">
        <RunTerminal runId={runId} onStatus={onStatus} />
      </Card>
    </div>
  );
}
