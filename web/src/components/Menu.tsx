import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/format";
import { Button } from "./ui";

export interface MenuItem {
  id: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  /** A short right-hand chip, such as "active" or a status. */
  trailing?: ReactNode;
  danger?: boolean;
  onSelect: () => void;
}

/**
 * A dropdown that is not clipped by anything.
 *
 * Every menu in Fenox was `position: absolute` inside a card, and cards use
 * `overflow: hidden` to round their corners — which clips the menu away the
 * moment it extends past the card, so it renders and is invisible. Moving the
 * panel onto `document.body` with `position: fixed` escapes every clipping and
 * stacking ancestor, so that class of bug cannot come back.
 *
 * It also brings what the hand-rolled versions each lacked: Escape, outside
 * click, scroll and resize, `aria-*`, and arrow-key navigation.
 */
export function Menu({
  items,
  children,
  header,
  label,
  align = "end",
  widthClass = "w-56",
  buttonVariant = "ghost",
  buttonSize = "sm",
  buttonClassName,
  title,
  disabled,
  onOpenChange,
}: {
  items: MenuItem[];
  children?: ReactNode;
  header?: string;
  label?: string;
  align?: "start" | "end";
  widthClass?: string;
  buttonVariant?: "primary" | "secondary" | "ghost" | "danger" | "success";
  buttonSize?: "sm" | "md" | "icon";
  buttonClassName?: string;
  title?: string;
  disabled?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const toggle = (next: boolean) => {
    setOpen(next);
    onOpenChange?.(next);
  };

  /** Place under the trigger, flip above when there is no room, clamp to screen. */
  const place = useCallback(() => {
    const anchor = trigger.current;
    const menu = panel.current;
    if (!anchor || !menu) return;
    const rect = anchor.getBoundingClientRect();
    const { offsetHeight: height, offsetWidth: width } = menu;
    const margin = 8;

    let top = rect.bottom + 4;
    if (top + height + margin > window.innerHeight) {
      const above = rect.top - height - 4;
      top = above >= margin ? above : Math.max(margin, window.innerHeight - height - margin);
    }
    let left = align === "end" ? rect.right - width : rect.left;
    left = Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - width - margin));
    setPosition({ top, left });
  }, [align]);

  useLayoutEffect(() => {
    if (open) {
      place();
      panel.current?.querySelector<HTMLElement>("[data-menuitem]")?.focus();
    } else {
      setPosition(null);
    }
  }, [open, place]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !trigger.current?.contains(target)) toggle(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const entries = Array.from(panel.current?.querySelectorAll<HTMLElement>("[data-menuitem]") ?? []);
      const index = entries.indexOf(document.activeElement as HTMLElement);
      if (event.key === "Escape") {
        event.stopPropagation();
        toggle(false);
        trigger.current?.focus();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        entries[(index + 1) % entries.length]?.focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        entries[(index - 1 + entries.length) % entries.length]?.focus();
      }
    };
    // A fixed panel would detach from a scrolled trigger, so close instead —
    // unless the scroll happened inside the panel itself.
    const onScroll = (event: Event) => {
      if (!panel.current?.contains(event.target as Node)) toggle(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, place]);

  return (
    <>
      <Button
        ref={trigger}
        type="button"
        variant={buttonVariant}
        size={buttonSize}
        className={buttonClassName}
        title={title}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          toggle(!open);
        }}
      >
        {children}
      </Button>

      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panel}
              role="menu"
              style={{ top: position?.top ?? -9999, left: position?.left ?? -9999 }}
              className={cn(
                "animate-in fixed z-[80] overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-panel)] py-1 shadow-2xl",
                widthClass,
                !position && "invisible",
              )}
              onClick={(event) => event.stopPropagation()}
            >
              {header ? (
                <p className="px-3 py-1 text-[10px] font-semibold tracking-wider text-[var(--color-subtle)] uppercase">
                  {header}
                </p>
              ) : null}
              {items.map((item, index) => (
                <button
                  key={item.id}
                  data-menuitem
                  role="menuitem"
                  tabIndex={-1}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    toggle(false);
                    item.onSelect();
                  }}
                  className={cn(
                    "flex w-full cursor-pointer items-start gap-2 px-3 py-1.5 text-left transition-colors",
                    item.danger
                      ? "text-[var(--color-danger)] hover:bg-[var(--color-danger)]/10"
                      : "text-[var(--color-muted)] hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]",
                    index === 0 && "focus:bg-[var(--color-panel-hover)]",
                  )}
                >
                  {item.icon ? <span className="mt-0.5 shrink-0">{item.icon}</span> : null}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{item.label}</span>
                    {item.hint ? (
                      <span className="block text-[10px] text-[var(--color-subtle)]">{item.hint}</span>
                    ) : null}
                  </span>
                  {item.trailing ? <span className="shrink-0">{item.trailing}</span> : null}
                </button>
              ))}
              {items.length === 0 ? (
                <p className="px-3 py-2 text-sm text-[var(--color-subtle)]">Nothing available</p>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
