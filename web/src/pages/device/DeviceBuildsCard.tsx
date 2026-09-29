import { useMutation, useQuery } from "@tanstack/react-query";
import { Hammer, Smartphone } from "lucide-react";
import { Link } from "react-router-dom";

import { installBuild, keys, listBuilds } from "@/api/queries";
import type { Device } from "@/api/types";
import { BuildStatus } from "@/components/builds";
import { Button, Card, EmptyState, SkeletonRows } from "@/components/ui";
import { formatBytes, timeAgo } from "@/lib/format";
import { toast } from "@/lib/toast";

/**
 * Built artifacts, ready to put on *this* device.
 *
 * The Builds page is where you go to look at builds; this is where you go to
 * put one on the phone in front of you. Picking the device is not a question
 * worth asking here — it is the page you are on.
 */
export function DeviceBuildsCard({ device }: { device: Device }) {
  const builds = useQuery({ queryKey: keys.builds, queryFn: () => listBuilds() });

  const install = useMutation({
    mutationFn: (buildId: string) => installBuild(buildId, device.id),
    onSuccess: (result) => toast.success(`Installed on ${result.device}`, result.artifact),
    onError: (error: Error) => toast.error("Could not install", error.message),
  });

  // Only what this device can actually take: no AABs, and nothing unfinished.
  const ready = (builds.data?.builds ?? [])
    .filter((build) => build.status === "succeeded" && build.installable && build.artifact_name)
    .slice(0, 6);

  return (
    <Card className="lg:col-span-2">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Hammer size={14} className="text-[var(--color-subtle)]" />
          <h2 className="text-sm font-semibold">Built apps</h2>
        </div>
        <Link to="/builds" className="text-xs text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]">
          All builds
        </Link>
      </div>

      {builds.isLoading ? (
        <div className="p-4">
          <SkeletonRows rows={3} />
        </div>
      ) : ready.length === 0 ? (
        <EmptyState
          icon={<Hammer size={20} />}
          title="Nothing built yet"
          description="Build a debug or release APK from a project and it appears here, ready to install on this phone."
          action={
            <Link to="/projects">
              <Button size="sm">Go to projects</Button>
            </Link>
          }
        />
      ) : (
        <div className="divide-y divide-[var(--color-border)]">
          {ready.map((build) => (
            <div key={build.id} className="flex items-center gap-3 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{build.artifact_name}</span>
                  <span className="shrink-0 text-[11px] text-[var(--color-subtle)]">{build.project}</span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-[var(--color-muted)]">
                  <BuildStatus status={build.status} />
                  <span className="tnum">{formatBytes(build.artifact_size)}</span>
                  <span className="tnum">{timeAgo(build.started_at)}</span>
                </div>
              </div>
              <Button
                size="sm"
                variant="secondary"
                className="shrink-0"
                disabled={!device.online || install.isPending}
                title={device.online ? `Install on ${device.id}` : "The device is offline"}
                onClick={() => install.mutate(build.id)}
              >
                <Smartphone size={13} />
                {install.isPending && install.variables === build.id ? "Installing…" : "Install"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
