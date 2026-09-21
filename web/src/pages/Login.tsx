import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { keys, login } from "@/api/queries";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";

export function LoginPage() {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);

  const signIn = useMutation({
    mutationFn: () => login(password, remember),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.auth }),
  });

  return (
    <div className="grid min-h-full place-items-center p-6">
      <Card className="w-full max-w-md p-8">
        <h1 className="text-xl font-semibold text-white">Sign in</h1>
        <p className="mt-2 text-sm text-[var(--color-muted)]">Enter the owner password for this Fenox installation.</p>
        <form
          className="mt-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (password) {
              signIn.mutate();
            }
          }}
        >
          <Field label="Password">
            <Input
              type="password"
              autoFocus
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
            <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
            Keep me signed in on this browser
          </label>
          <ErrorText>{(signIn.error as Error | null)?.message}</ErrorText>
          <Button type="submit" className="w-full justify-center" disabled={signIn.isPending || !password}>
            {signIn.isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
