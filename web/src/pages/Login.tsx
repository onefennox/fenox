import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, LogIn } from "lucide-react";
import { useState } from "react";

import { keys, login } from "@/api/queries";
import { AuthShell } from "@/components/AuthShell";
import { Button, ErrorText, Field, Input, Switch } from "@/components/ui";

export function LoginPage() {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [reveal, setReveal] = useState(false);

  const signIn = useMutation({
    mutationFn: () => login(password, remember),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.auth }),
  });

  return (
    <AuthShell
      title="Sign in"
      description="This installation has a single owner account."
      footer="Locked out? Run `fenox auth reset` on the machine hosting Fenox."
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (password) signIn.mutate();
        }}
      >
        <Field label="Password">
          <div className="relative">
            <Input
              type={reveal ? "text" : "password"}
              autoFocus
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="pr-9"
            />
            <button
              type="button"
              onClick={() => setReveal((current) => !current)}
              aria-label={reveal ? "Hide password" : "Show password"}
              className="absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer rounded p-1 text-[var(--color-subtle)] transition-colors hover:text-[var(--color-text)]"
            >
              {reveal ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </Field>

        <div className="flex items-center justify-between">
          <span className="text-xs text-[var(--color-muted)]">Stay signed in</span>
          <Switch checked={remember} onChange={setRemember} label="Stay signed in" />
        </div>

        <ErrorText>{(signIn.error as Error | null)?.message}</ErrorText>

        <Button type="submit" className="w-full justify-center" disabled={signIn.isPending || !password}>
          <LogIn size={14} />
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthShell>
  );
}
