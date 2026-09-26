import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Info, Wrench } from "lucide-react";
import { useState } from "react";

import { getConnection, keys, repairConnection } from "@/api/queries";
import type { ConnectionFinding } from "@/api/types";
import { Button, Card, Spinner } from "@/components/ui";

const TONES = {
  error: { border: "border-red-500/40", text: "text-red-300", icon: AlertTriangle },
  warn: { border: "border-amber-500/40", text: "text-amber-300", icon: AlertTriangle },
  info: { border: "border-[var(--color-border)]", text: "text-[var(--color-muted)]", icon: Info },
} as const;

/** The commands for one finding, as a single copyable block. */
function commandsFor(finding: ConnectionFinding): string {
  return [finding.fix, ...finding.also].filter(Boolean).join("\n");
}

/** How a fix attempt turned out, said plainly. */
type FixState = "resolved" | "escalated" | "unchanged" | "blocked";

const OUTCOME: Record<FixState, { text: string; tone: string }> = {
  resolved: { text: "Fixed", tone: "text-emerald-300" },
  escalated: { text: "Narrowed it down — not fixed yet", tone: "text-amber-300" },
  unchanged: { text: "No change", tone: "text-amber-300" },
  blocked: { text: "This one needs you", tone: "text-[var(--color-muted)]" },
};

function FindingCard({ finding }: { finding: ConnectionFinding }) {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [outcome, setOutcome] = useState<{ state: FixState; first?: string; next?: string } | null>(null);
  const repair = useMutation({
    mutationFn: () => repairConnection(finding.id),
    onSuccess: (result) => {
      const next = result.remaining.find((item) => item.id !== finding.id);
      setOutcome({
        state: result.state as FixState,
        first: String(result.detail || "").split("\n")[0],
        next: next ? next.title : undefined,
      });
      queryClient.invalidateQueries({ queryKey: keys.connection });
    },
  });
  const tone = TONES[finding.severity] ?? TONES.info;
  const Icon = tone.icon;
  const commands = commandsFor(finding);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(commands);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be refused; the text is on screen either way.
    }
  };

  return (
    <Card className={`space-y-3 border p-4 ${tone.border}`}>
      <div className="flex items-start gap-3">
        <Icon size={16} className={`mt-0.5 shrink-0 ${tone.text}`} />
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-medium ${tone.text}`}>{finding.title}</p>
          <p className="mt-1 text-sm text-[var(--color-muted)]">{finding.detail}</p>
        </div>
      </div>

      {commands ? (
        <div className="flex items-start gap-2">
          <pre className="min-w-0 flex-1 overflow-x-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-white">
            {finding.runs_in === "windows" ? `# in an Administrator PowerShell on Windows\n${commands}` : commands}
          </pre>
          <Button type="button" variant="ghost" onClick={copy} title="Copy">
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </Button>
        </div>
      ) : null}

      {finding.auto ? (
        <div className="flex items-center gap-2">
          <Button type="button" variant="secondary" onClick={() => repair.mutate()} disabled={repair.isPending}>
            <Wrench size={14} />
            {repair.isPending ? "Working…" : "Let Fenox fix this"}
          </Button>
          <span className="text-xs text-[var(--color-muted)]">No command needed — Fenox can do this one itself.</span>
        </div>
      ) : null}
      {repair.error ? <p className="text-sm text-red-400">{(repair.error as Error).message}</p> : null}

      {outcome ? (
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm">
          <p className={`font-medium ${OUTCOME[outcome.state].tone}`}>{OUTCOME[outcome.state].text}</p>
          {outcome.first ? <p className="mt-1 text-xs text-[var(--color-muted)]">{outcome.first}</p> : null}
          {outcome.next ? <p className="mt-1 text-xs text-[var(--color-muted)]">Next: {outcome.next}</p> : null}
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Why devices are not reachable, and the one thing to do about each.
 *
 * Shown above the connection flows on purpose: a phone that is plugged in but
 * invisible looks identical to no phone at all, so the explanation has to come
 * before the instructions rather than after a failed scan.
 */
export function ConnectionPanel() {
  const { data, isLoading } = useQuery({ queryKey: keys.connection, queryFn: getConnection });

  if (isLoading) {
    return <Spinner label="Checking device connections" />;
  }

  const findings = data?.findings ?? [];
  if (!findings.length) {
    return (
      <Card className="flex items-center gap-2 border-emerald-500/30 p-3 text-sm text-emerald-300">
        <Check size={16} />
        Nothing is blocking device connections.
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {findings.map((finding) => (
        <FindingCard key={finding.id} finding={finding} />
      ))}
    </div>
  );
}

/** Phones currently showing a pairing code, which is when help is most useful. */
export function PairingPrompt() {
  const { data } = useQuery({ queryKey: keys.connection, queryFn: getConnection });
  const pairing = data?.wireless.pairing ?? [];
  if (!pairing.length) {
    return null;
  }
  return (
    <Card className="border-[var(--color-accent)]/40 p-3 text-sm">
      <p className="font-medium text-white">A phone is ready to pair</p>
      <p className="mt-1 text-[var(--color-muted)]">
        Enter the code shown on the phone. Its address is filled in for you.
      </p>
      <ul className="mt-2 space-y-1 font-mono text-xs text-white">
        {pairing.map((service) => (
          <li key={`${service.ip}:${service.port}`}>
            {service.ip}:{service.port}
          </li>
        ))}
      </ul>
    </Card>
  );
}
