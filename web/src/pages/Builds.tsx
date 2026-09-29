import { useQuery } from "@tanstack/react-query";
import { Hammer } from "lucide-react";

import { keys, listBuilds } from "@/api/queries";
import { BuildRow } from "@/components/builds";
import { Card, EmptyState, SkeletonRows } from "@/components/ui";

/**
 * Every build, across every project.
 *
 * Useful on its own, and the reason it exists rather than only a per-project
 * tab: a build takes minutes, so it is started and then left. This is where you
 * come back to check on it without knowing which project it belonged to.
 */
export function BuildsPage() {
  const { data, isLoading } = useQuery({
    queryKey: keys.builds,
    queryFn: () => listBuilds(),
    refetchInterval: (query) =>
      (query.state.data?.builds ?? []).some((build) => build.status === "running") ? 2000 : 10000,
  });

  const builds = data?.builds ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Builds</h1>
        <p className="mt-0.5 text-sm text-[var(--color-muted)]">
          Every artifact built from your projects, ready to download.
        </p>
      </div>

      <Card>
        {isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : builds.length === 0 ? (
          <EmptyState
            icon={<Hammer size={22} />}
            title="No builds yet"
            description="Open a project and build a debug or release APK — it will appear here with a download link."
          />
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {builds.map((build) => (
              <BuildRow key={build.id} build={build} showProject />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
