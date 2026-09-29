import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Hammer, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { keys, listBuilds } from "@/api/queries";
import type { Build } from "@/api/types";
import { BuildLauncher, BuildRow, BuildStatus } from "@/components/builds";
import { Card, EmptyState, SkeletonRows } from "@/components/ui";
import { formatBytes, timeAgo } from "@/lib/format";

/**
 * Streams a build's output.
 *
 * The WebSocket replays the transcript on connect, so a viewer that opens the
 * page halfway through a build still sees what happened rather than joining
 * mid-sentence.
 */
function useBuildLog(buildId: string | null, onFinished: () => void) {
  const [lines, setLines] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => {
    if (!buildId) {
      setLines([]);
      setDone(false);
      return;
    }
    setLines([]);
    setDone(false);
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/builds/${encodeURIComponent(buildId)}`);

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "log") {
        setLines((current) => (current.length > 5000 ? [...current.slice(-4000), message.line] : [...current, message.line]));
      } else if (message.type === "exit") {
        setDone(true);
        finished.current();
      }
    };
    socket.onerror = () => setDone(true);
    return () => socket.close();
  }, [buildId]);

  return { lines, done };
}

function LogView({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLPreElement>(null);
  // Follow the tail, but only while the reader is already at the bottom, so
  // scrolling up to read something does not get yanked away.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    if (atBottom) node.scrollTop = node.scrollHeight;
  }, [lines]);

  return (
    <pre
      ref={ref}
      className="scroll-thin max-h-80 overflow-auto rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--color-muted)]"
    >
      {lines.length ? lines.join("\n") : "Waiting for output…"}
    </pre>
  );
}

export function BuildsPanel({ project }: { project: string }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);

  const builds = useQuery({
    queryKey: keys.builds,
    queryFn: () => listBuilds(),
    refetchInterval: (query) =>
      (query.state.data?.builds ?? []).some((build) => build.project === project && build.status === "running")
        ? 1500
        : 8000,
  });

  const mine = (builds.data?.builds ?? []).filter((build) => build.project === project);
  const running = mine.find((build) => build.status === "running") ?? null;
  const active = selected ? mine.find((build) => build.id === selected) ?? null : null;
  const watch = running ?? active;

  const { lines, done } = useBuildLog(watch?.id ?? null, () => {
    queryClient.invalidateQueries({ queryKey: keys.builds });
  });

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Build an artifact</h2>
            <p className="mt-0.5 text-xs text-[var(--color-muted)]">
              Builds run here, on this machine. No device needed.
            </p>
          </div>
        </div>
        <BuildLauncher project={project} kinds={builds.data?.kinds ?? []} busy={Boolean(running)} />
      </Card>

      {watch ? (
        <Card className="p-4">
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Terminal size={14} className="text-[var(--color-subtle)]" />
              <span className="text-sm font-medium">{watch.label}</span>
              <BuildStatus status={done && watch.status === "running" ? "succeeded" : watch.status} />
            </div>
            <span className="tnum text-xs text-[var(--color-subtle)]">
              {watch.artifact_size ? formatBytes(watch.artifact_size) : timeAgo(watch.started_at)}
            </span>
          </div>
          <LogView lines={lines} />
        </Card>
      ) : null}

      <Card>
        <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2.5">
          <h2 className="text-sm font-semibold">Artifacts</h2>
          <span className="tnum text-xs text-[var(--color-subtle)]">{mine.length}</span>
        </div>
        {builds.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : mine.length === 0 ? (
          <EmptyState
            icon={<Hammer size={20} />}
            title="Nothing built yet"
            description="Pick a build above. The APK or AAB appears here with a download button when it finishes."
          />
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {mine.map((build) => (
              <BuildRow
                key={build.id}
                build={build}
                active={watch?.id === build.id}
                onOpen={() => setSelected(build.id === selected ? null : build.id)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export type { Build };
