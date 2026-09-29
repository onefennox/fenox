import { useQuery } from "@tanstack/react-query";
import { Download, FileVideo, ImageIcon } from "lucide-react";

import { keys, listCaptures } from "@/api/queries";
import { Card, EmptyState, Skeleton } from "@/components/ui";
import { formatBytes, timeAgo } from "@/lib/format";

/**
 * Screenshots and recordings Fenox has taken.
 *
 * They were always being saved to disk, but nowhere said so — which made them
 * effectively lost. This lists them with a download link, newest first.
 */
export function CapturesCard() {
  const captures = useQuery({
    queryKey: keys.captures,
    queryFn: listCaptures,
    refetchInterval: 15000,
  });

  const items = captures.data?.captures ?? [];

  return (
    <Card className="lg:col-span-2">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-2.5">
        <div>
          <h2 className="text-sm font-semibold">Captures</h2>
          {captures.data?.directory ? (
            <p className="truncate font-mono text-[10px] text-[var(--color-subtle)]">{captures.data.directory}</p>
          ) : null}
        </div>
        <span className="tnum text-xs text-[var(--color-subtle)]">{items.length}</span>
      </div>

      {captures.isLoading ? (
        <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-24" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ImageIcon size={20} />}
          title="No captures yet"
          description="Screenshots and recordings you take from the screen panel land here."
        />
      ) : (
        <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.slice(0, 12).map((capture) => {
            const isImage = capture.kind === "screenshot";
            return (
              <a
                key={capture.path}
                href={`/api/system/captures/download?path=${encodeURIComponent(capture.path)}`}
                download
                className="group relative overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] transition-colors hover:border-[var(--color-accent)]/50"
              >
                <div className="grid h-24 place-items-center">
                  {isImage ? (
                    // The file is served by the hub, so the browser can render it directly.
                    <img
                      src={`/api/system/captures/download?path=${encodeURIComponent(capture.path)}`}
                      alt={capture.name}
                      loading="lazy"
                      className="h-24 w-full object-cover"
                    />
                  ) : (
                    <FileVideo size={20} className="text-[var(--color-subtle)]" />
                  )}
                </div>
                <div className="flex items-center gap-1.5 border-t border-[var(--color-border)] px-2 py-1.5">
                  <span className="min-w-0 flex-1 truncate text-[10px] text-[var(--color-muted)]">{capture.name}</span>
                  <span className="tnum shrink-0 text-[10px] text-[var(--color-subtle)]">
                    {formatBytes(capture.size, 0)}
                  </span>
                  <Download
                    size={11}
                    className="shrink-0 text-[var(--color-subtle)] opacity-0 transition-opacity group-hover:opacity-100"
                  />
                </div>
                <span className="tnum absolute top-1.5 right-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[9px] text-[var(--color-text)] opacity-0 transition-opacity group-hover:opacity-100">
                  {timeAgo(capture.at)}
                </span>
              </a>
            );
          })}
        </div>
      )}
    </Card>
  );
}
