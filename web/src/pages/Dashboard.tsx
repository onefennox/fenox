import { useQuery } from "@tanstack/react-query";
import { Hammer, Loader2, Play, Smartphone } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { getActivity, keys, listDevices, listProjects } from "@/api/queries";
import type { ActivityItem } from "@/api/types";
import { Badge, Card, EmptyState, SkeletonRows, StatusDot } from "@/components/ui";
import { cn, formatNumber, timeAgo } from "@/lib/format";
import { useActiveDevice } from "@/hooks/useActiveDevice";

const STATUS_TONE: Record<string, "accent" | "success" | "danger" | "default" | "warn"> = {
  running: "accent",
  starting: "accent",
  succeeded: "success",
  finished: "success",
  online: "success",
  failed: "danger",
  crashed: "danger",
  offline: "default",
  cancelled: "default",
  lost: "warn",
  stopped: "default",
};

const KIND_ICON: Record<ActivityItem["kind"], LucideIcon> = {
  build: Hammer,
  run: Play,
  device: Smartphone,
};

function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "accent" | "success";
}) {
  return (
    <Card className="p-4" interactive>
      <div
        className={cn(
          "tnum text-2xl font-semibold tracking-tight",
          tone === "accent" && "text-[var(--color-accent)]",
          tone === "success" && "text-[var(--color-success)]",
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 text-xs text-[var(--color-muted)]">{label}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-[var(--color-subtle)]">{hint}</div> : null}
    </Card>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const Icon = KIND_ICON[item.kind] ?? Hammer;
  const tone = STATUS_TONE[item.status] ?? "default";
  const spinning = item.status === "running" || item.status === "starting";

  return (
    <Link
      to={item.href}
      className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-[var(--color-panel-hover)]"
    >
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-[var(--radius-md)] bg-[var(--color-elevated)]">
        <Icon size={13} className="text-[var(--color-muted)]" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{item.title}</p>
        <p className="truncate text-[11px] text-[var(--color-subtle)]">{item.detail}</p>
      </div>
      <Badge tone={tone}>
        {spinning ? <Loader2 size={10} className="animate-spin" /> : null}
        {item.status || item.kind}
      </Badge>
      <span className="tnum hidden w-16 shrink-0 text-right text-[11px] text-[var(--color-subtle)] sm:block">
        {timeAgo(item.at)}
      </span>
    </Link>
  );
}

export function DashboardPage() {
  const { setActiveDevice } = useActiveDevice();
  const devices = useQuery({ queryKey: keys.devices, queryFn: listDevices, refetchInterval: 5000 });
  const projects = useQuery({ queryKey: keys.projects, queryFn: listProjects });
  const activity = useQuery({ queryKey: keys.activity, queryFn: getActivity, refetchInterval: 5000 });

  const list = devices.data?.devices ?? [];
  const online = list.filter((device) => device.online && !device.disabled);
  const pending = devices.data?.pending ?? [];
  const projectCount = Object.keys(projects.data?.projects ?? {}).length;
  const builds = (activity.data?.items ?? []).filter((item) => item.kind === "build");
  const runs = (activity.data?.items ?? []).filter((item) => item.kind === "run");
  const feed = activity.data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">
            Devices, projects and everything that has been running.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/connect"
            className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--color-accent)] px-3.5 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
          >
            Connect a device
          </Link>
          <Link
            to="/projects"
            className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-border)] px-3.5 text-sm font-medium text-[var(--color-muted)] transition-colors hover:border-[var(--color-border-strong)] hover:text-[var(--color-text)]"
          >
            Projects
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Devices online" value={online.length} tone={online.length ? "success" : "default"} />
        <Stat label="Registered devices" value={list.length} />
        <Stat label="Projects" value={projectCount} />
        <Stat
          label="Active runs"
          value={runs.filter((run) => run.status === "running" || run.status === "starting").length}
          tone="accent"
        />
      </div>

      {pending.length > 0 ? (
        <Card className="border-[var(--color-warning)]/40 bg-[var(--color-warning)]/5 p-3">
          <p className="text-sm text-[var(--color-warning)]">
            {pending.length === 1 ? "One device is" : `${pending.length} devices are`} visible but not usable. Accept
            the debugging prompt on the phone.
          </p>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2.5">
            <h2 className="text-sm font-semibold">Recent activity</h2>
            <Link to="/builds" className="text-xs text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]">
              All builds
            </Link>
          </div>
          {activity.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={5} />
            </div>
          ) : feed.length === 0 ? (
            <EmptyState
              icon={<Hammer size={20} />}
              title="Nothing has happened yet"
              description="Connect a device or build a project and it shows up here."
            />
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {feed.slice(0, 10).map((item) => (
                <ActivityRow key={`${item.kind}-${item.id}`} item={item} />
              ))}
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2.5">
              <h2 className="text-sm font-semibold">Devices</h2>
              <span className="tnum text-xs text-[var(--color-subtle)]">
                {online.length}/{list.length}
              </span>
            </div>
            {devices.isLoading ? (
              <div className="p-4">
                <SkeletonRows rows={3} />
              </div>
            ) : list.length === 0 ? (
              <EmptyState
                icon={<Smartphone size={20} />}
                title="No devices yet"
                description="Wireless debugging needs nothing installed. USB on WSL needs the bridge."
              />
            ) : (
              <div className="divide-y divide-[var(--color-border)]">
                {list.slice(0, 6).map((device) => (
                  <button
                    key={device.id}
                    onClick={() => setActiveDevice(device.id)}
                    className="flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-[var(--color-panel-hover)]"
                  >
                    <StatusDot online={device.online} disabled={device.disabled} />
                    <span className="min-w-0 flex-1 truncate text-sm">{device.id}</span>
                    <span className="truncate text-[11px] text-[var(--color-subtle)]">{device.model ?? device.type}</span>
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-3">
            <h2 className="mb-2 text-sm font-semibold">At a glance</h2>
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--color-muted)]">Builds recorded</span>
                <span className="tnum">{formatNumber(builds.length)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-muted)]">Runs recorded</span>
                <span className="tnum">{formatNumber(runs.length)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-muted)]">Awaiting authorisation</span>
                <span className="tnum">{pending.length}</span>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
