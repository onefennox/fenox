import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { keys, setupOwner } from "@/api/queries";
import { AuthShell } from "@/components/AuthShell";
import { Button, ErrorText, Field, Input } from "@/components/ui";
import { cn } from "@/lib/format";

/** A quiet strength hint — advice, not a gate, so it never blocks a decision. */
function strength(password: string): { label: string; tone: string; bars: number } {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  const bars = Math.min(score, 4);
  const tones = ["bg-[var(--color-danger)]", "bg-[var(--color-warning)]", "bg-[var(--color-warning)]", "bg-[var(--color-success)]"];
  const labels = ["Very weak", "Weak", "Fair", "Good", "Strong"];
  return { label: labels[bars] ?? "", tone: tones[Math.max(bars - 1, 0)], bars };
}

export function SetupPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const create = useMutation({
    mutationFn: () => setupOwner(password),
    onSuccess: () => {
      // The first useful action is connecting a phone, so go straight there.
      queryClient.setQueryData(keys.auth, { configured: true, authenticated: true });
      navigate("/connect", { replace: true });
    },
  });

  const validation =
    password.length < 6 ? "Password must be at least 6 characters." : password !== confirm ? "Passwords do not match." : "";
  const meter = strength(password);

  return (
    <AuthShell
      title="Set up Fenox"
      description="Choose the password that protects this installation. You will use it to sign in."
      footer="Fenox runs commands on this machine, so treat this password like an SSH key."
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!validation) create.mutate();
        }}
      >
        <Field label="Owner password">
          <Input
            type="password"
            autoFocus
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        {password ? (
          <div className="flex items-center gap-2">
            <div className="flex flex-1 gap-1">
              {[0, 1, 2, 3].map((index) => (
                <span
                  key={index}
                  className={cn(
                    "h-1 flex-1 rounded-full transition-colors",
                    index < meter.bars ? meter.tone : "bg-[var(--color-border)]",
                  )}
                />
              ))}
            </div>
            <span className="w-16 shrink-0 text-right text-[11px] text-[var(--color-subtle)]">{meter.label}</span>
          </div>
        ) : null}

        <Field label="Confirm password">
          <Input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </Field>

        {password && password === confirm && !validation ? (
          <p className="flex items-center gap-1.5 text-xs text-[var(--color-success)]">
            <Check size={12} />
            Passwords match
          </p>
        ) : null}

        <ErrorText>{validation || (create.error as Error | null)?.message}</ErrorText>

        <Button type="submit" className="w-full justify-center" disabled={create.isPending || Boolean(validation)}>
          <ShieldCheck size={14} />
          {create.isPending ? "Setting up…" : "Set password"}
        </Button>
      </form>
    </AuthShell>
  );
}
