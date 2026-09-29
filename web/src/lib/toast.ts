import { create } from "zustand";

/**
 * Transient notifications.
 *
 * Fenox does a lot in the background — builds finish, devices drop, artifacts
 * appear — and a message is the difference between the app doing something and
 * the app appearing to do nothing. Kept deliberately small: a list, a push, a
 * dismiss, and auto-expiry. Anything that needs to persist belongs in the page,
 * not in a toast.
 */
export type ToastTone = "info" | "success" | "error";

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastState {
  items: Toast[];
  push: (toast: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
}

let counter = 0;

export const useToasts = create<ToastState>((set) => ({
  items: [],
  push: (toast) => {
    const id = `t${++counter}`;
    set((state) => ({ items: [...state.items, { ...toast, id }].slice(-4) }));
    return id;
  },
  dismiss: (id) => set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
}));

/** Imperative helper, so a mutation callback does not need a hook. */
export const toast = {
  info: (title: string, description?: string) => useToasts.getState().push({ tone: "info", title, description }),
  success: (title: string, description?: string) =>
    useToasts.getState().push({ tone: "success", title, description }),
  error: (title: string, description?: string) => useToasts.getState().push({ tone: "error", title, description }),
};
