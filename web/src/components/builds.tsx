import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  Hammer,
  Loader2,
  Trash2,
  XCircle,
  Ban,
  ChevronRight,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { artifactUrl, cancelBuild, deleteBuild, keys, startBuild } from "@/api/queries";
import type { Build, BuildKind } from "@/api/types";
import { Badge } from "@/components/ui";
import { cn, formatBytes, timeAgo } from "@/lib/format";
import { toast } from "@/lib/toast";

const STATUS: Record<
  Build["status"],
  { label: string; tone: "default" | "accent" | "success" | "danger"; icon: LucideIcon; className: string }
> = {
  running: { label: "Building", tone: "accent", icon: Loader2, className: "text-[var(--color-accent)]" },
  succeeded: { label: "Succeeded", tone: "success", icon: CheckCircle2, className: "text-[var(--color-success)]" },
  failed: { label: "Failed", tone: "danger", icon: XCircle, className: "text-[var(--color-danger)]" },
  cancelled: { label: "Cancelled", tone: "default", icon: Ban, className: "text-[var(--color-subtle)]" },
};

export function BuildStatus({ status }: { status: Build["status"] }) {
  const spec = STATUS[status] ?? STATUS.cancelled;
  const Icon = spec.icon;
  return (
    <Badge tone={spec.tone}>
      <Icon size={11} className={cn(status === "running" && "animate-spin")} />
      {spec.label}
    </Badge>
  );
}

/**
 * The build actions.
 *
 * Each kind says what it is for, because "appbundle" means nothing to most
 * people and the difference between debug and release is the difference between
 * an app you can share and one you cannot.
 */
export function BuildLauncher({
  project,
  kinds,
  busy,
  compact = false,
}: {
  project: string;
  kinds: BuildKind[];
  busy?: boolean;
  compact?: boolean;
}) {
  const queryClient = useQueryClient();

  const start = useMutation({
    mutationFn: (kind: string) => startBuild(project, kind),
    onSuccess: (build) => {
      toast.info(`Started ${build.label}`, build.project);
      queryClient.invalidateQueries({ queryKey: keys.builds });
    },
    onError: (error: Error) => toast.error("Could not start the build", error.message),
  });

  return (
    <div className={cn("flex flex-wrap gap-2")}>
      {kinds.map((kind) => {
        const isAab = kind.id.includes("aab");
        return (
          <button
            key={kind.id}
            type="button"
            title={kind.hint}
            disabled={start.isPending || busy}
            onClick={() => start.mutate(kind.id)}
            className={cn(
              "group flex cursor-pointer flex-col items-start rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-elevated)] px-3 py-2 text-left transition-colors",
              "hover:border-[var(--color-accent)]/50 hover:bg-[var(--color-panel-hover)] disabled:cursor-not-allowed disabled:opacity-50",
              compact && "px-2.5 py-1.5",
            )}
          >
            <span className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-text)]">
              <Hammer size={12} className="text-[var(--color-accent)]" />
              {kind.label}
            </span>
            {compact ? null : (
              <span className="mt-0.5 max-w-[22ch] text-[10px] leading-tight text-[var(--color-subtle)]">
                {isAab ? "Play Store format" : kind.hint}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** One build as a dense row: artifact, size, age, status, actions. */
export function BuildRow({
  build,
  showProject = false,
  onOpen,
  active = false,
}: {
  build: Build;
  showProject?: boolean;
  onOpen?: () => void;
  active?: boolean;
}) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.builds });

  const cancel = useMutation({
    mutationFn: () => cancelBuild(build.id),
    onSuccess: () => {
      toast.info("Cancelling…", build.label);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteBuild(build.id),
    onSuccess: () => {
      toast.success("Build deleted");
      refresh();
    },
  });

  const ready = build.status === "succeeded" && build.artifact_name;

  return (
    <div
      className={cn(
        "group flex items-center gap-3 px-3 py-2.5 transition-colors",
        onOpen && "cursor-pointer hover:bg-[var(--color-panel-hover)]",
        active && "bg-[var(--color-accent-soft)]",
      )}
      onClick={onOpen}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-[var(--color-text)]">
            {build.artifact_name || build.label}
          </span>
          {showProject ? (
            <span className="shrink-0 text-xs text-[var(--color-subtle)]">{build.project}</span>
          ) : (
            <span className="shrink-0 text-xs text-[var(--color-subtle)]">{build.label}</span>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--color-muted)]">
          {ready ? <span className="tnum">{formatBytes(build.artifact_size)}</span> : null}
          <span className="tnum">{timeAgo(build.started_at)}</span>
          {build.error ? <span className="truncate text-[var(--color-danger)]">{build.error}</span> : null}
        </div>
      </div>

      <BuildStatus status={build.status} />

      <div className="flex shrink-0 items-center gap-1" onClick={(event) => event.stopPropagation()}>
        {ready ? (
          <a
            href={artifactUrl(build.id)}
            download
            className="inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] px-2.5 text-xs font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
          >
            <Download size={12} />
            Download
          </a>
        ) : build.status === "running" ? (
          <button
            onClick={() => cancel.mutate()}
            className="cursor-pointer rounded-[var(--radius-md)] px-2 py-1 text-xs text-[var(--color-muted)] transition-colors hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
          >
            Cancel
          </button>
        ) : null}
        {build.status !== "running" ? (
          <button
            onClick={() => remove.mutate()}
            aria-label="Delete build"
            className="cursor-pointer rounded-[var(--radius-md)] p-1.5 text-[var(--color-subtle)] opacity-0 transition-colors group-hover:opacity-100 hover:text-[var(--color-danger)]"
          >
            <Trash2 size={13} />
          </button>
        ) : null}
        {onOpen ? <ChevronRight size={14} className="shrink-0 text-[var(--color-subtle)]" /> : null}
      </div>
    </div>
  );
}
