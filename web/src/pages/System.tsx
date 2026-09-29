import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, RefreshCw, Wrench } from "lucide-react";
import { useState } from "react";

import { getDoctor, installTool } from "@/api/queries";
import type { ToolCheck } from "@/api/types";
import { Badge, Button, Card, ErrorText, SkeletonRows } from "@/components/ui";
import { cn } from "@/lib/format";

function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 flex items-start gap-2">
      <pre className="scroll-thin min-w-0 flex-1 overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 font-mono text-xs text-[var(--color-text)]">
        {command}
      </pre>
      <Button
        variant="ghost"
        size="icon"
        title="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(command);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            // Clipboard can be refused; the command is on screen either way.
          }
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </Button>
    </div>
  );
}

function ToolRow({ tool, onInstall, busy }: { tool: ToolCheck; onInstall: () => void; busy: boolean }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-[var(--color-panel-hover)]">
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          tool.present
            ? "bg-[var(--color-success)]"
            : tool.required
              ? "bg-[var(--color-danger)]"
              : "bg-[var(--color-subtle)]",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{tool.name}</span>
          {tool.required ? <Badge tone="accent">required</Badge> : <Badge>optional</Badge>}
        </div>
        <p className="truncate text-xs text-[var(--color-muted)]">
          {tool.present ? tool.version || tool.path : tool.purpose}
        </p>
      </div>
      {!tool.present ? (
        tool.manual ? (
          <a
            className="shrink-0 text-xs text-[var(--color-accent)] hover:underline"
            href={tool.manual}
            target="_blank"
            rel="noreferrer"
          >
            Install guide
          </a>
        ) : (
          <Button size="sm" variant="secondary" onClick={onInstall} disabled={busy}>
            Install
          </Button>
        )
      ) : null}
    </div>
  );
}

export function SystemPage() {
  const queryClient = useQueryClient();
  const doctor = useQuery({ queryKey: ["doctor"], queryFn: getDoctor });
  const [command, setCommand] = useState<{ tool: string; command: string; note?: string } | null>(null);

  const install = useMutation({
    mutationFn: installTool,
    onSuccess: (result, tool) => {
      if (result.requires_sudo && result.command) {
        // Fenox never runs sudo, so this becomes a command for the owner.
        setCommand({ tool, command: result.command, note: result.note });
      } else {
        setCommand(null);
        queryClient.invalidateQueries({ queryKey: ["doctor"] });
      }
    },
    onError: (error: Error) => setCommand({ tool: "", command: error.message }),
  });

  if (doctor.error || (!doctor.isLoading && !doctor.data)) {
    return <ErrorText>{(doctor.error as Error | null)?.message ?? "Doctor unavailable."}</ErrorText>;
  }

  const report = doctor.data;
  const missing = report?.tools.filter((tool) => !tool.present) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Diagnostics</h1>
          <p className="mt-0.5 text-sm text-[var(--color-muted)]">
            What Fenox found on this machine. Anything needing root is given to you as a command to run.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => queryClient.invalidateQueries({ queryKey: ["doctor"] })}>
          <RefreshCw size={13} />
          Re-check
        </Button>
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-[var(--color-muted)]">
          <span className="font-medium text-[var(--color-text)]">
            {report?.platform.wsl ? "WSL" : report?.platform.linux ? "Linux" : "Unknown"}
          </span>
          <span>
            adb port <span className="tnum text-[var(--color-text)]">{report?.adb.server_port}</span>
          </span>
          <span>
            Windows adb{" "}
            <span className="text-[var(--color-text)]">{report?.adb.windows_exe ? "found" : "not found"}</span>
          </span>
          <span>
            missing <span className="tnum text-[var(--color-text)]">{missing.length}</span>
          </span>
        </div>
        {report?.notes.map((note) => (
          <p
            key={note.text}
            className={cn(
              "mt-2 text-sm",
              note.tone === "warn" ? "text-[var(--color-warning)]" : "text-[var(--color-success)]",
            )}
          >
            {note.text}
          </p>
        ))}
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-2.5">
          <Wrench size={14} className="text-[var(--color-subtle)]" />
          <h2 className="text-sm font-semibold">Tools</h2>
          <span className="tnum ml-auto text-xs text-[var(--color-subtle)]">{report?.tools.length ?? 0}</span>
        </div>
        {doctor.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={6} />
          </div>
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {report?.tools.map((tool) => (
              <ToolRow
                key={tool.name}
                tool={tool}
                onInstall={() => install.mutate(tool.name)}
                busy={install.isPending}
              />
            ))}
          </div>
        )}
      </Card>

      {command ? (
        <Card className="border-[var(--color-warning)]/40 p-4">
          <p className="text-sm text-[var(--color-warning)]">
            {command.tool ? `Installing ${command.tool} needs root.` : "That did not work."} Run this yourself:
          </p>
          {command.note ? <p className="mt-1 text-xs text-[var(--color-muted)]">{command.note}</p> : null}
          <CopyCommand command={command.command} />
        </Card>
      ) : null}

      {install.data?.output ? (
        <Card className="p-4">
          <pre className="scroll-thin max-h-48 overflow-auto font-mono text-[11px] whitespace-pre-wrap text-[var(--color-muted)]">
            {install.data.output}
          </pre>
        </Card>
      ) : null}
    </div>
  );
}
