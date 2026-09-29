import type { ReactNode } from "react";

/**
 * The frame both unauthenticated pages sit in.
 *
 * These are the only screens someone sees before they trust the tool with their
 * phones, so they get a deliberate one: a quiet background, the mark, and the
 * form on a raised panel. Kept in one place so sign-in and first-run setup
 * cannot drift apart.
 */
export function AuthShell({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="relative grid min-h-full place-items-center overflow-hidden p-6">
      {/* Two soft radial washes rather than an image: no asset to load, and it
          reads the same in either theme. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -left-32 h-[28rem] w-[28rem] rounded-full opacity-[0.13] blur-3xl"
        style={{ background: "radial-gradient(circle, var(--color-accent), transparent 70%)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-32 -bottom-40 h-[28rem] w-[28rem] rounded-full opacity-[0.10] blur-3xl"
        style={{ background: "radial-gradient(circle, var(--color-accent), transparent 70%)" }}
      />

      <div className="animate-in relative w-full max-w-[26rem]">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="grid h-11 w-11 place-items-center rounded-[var(--radius-lg)] bg-[var(--color-accent)] text-lg font-bold text-white shadow-lg">
            F
          </span>
          <span className="mt-3 text-sm font-semibold tracking-tight">Fenox</span>
          <span className="text-xs text-[var(--color-subtle)]">Devices and Flutter, from the browser</span>
        </div>

        <div className="rounded-[var(--radius-xl)] border border-[var(--color-border)] bg-[var(--color-panel)] p-6 shadow-2xl">
          <h1 className="text-base font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-xs text-[var(--color-muted)]">{description}</p>
          <div className="mt-5">{children}</div>
        </div>

        {footer ? <div className="mt-4 text-center text-[11px] text-[var(--color-subtle)]">{footer}</div> : null}
      </div>
    </div>
  );
}
