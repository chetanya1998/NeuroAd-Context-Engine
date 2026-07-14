import { clsx } from "clsx";

export function Card({
  children,
  className
}: Readonly<{ children: React.ReactNode; className?: string }>) {
  return <div className={clsx("rounded-lg border border-border bg-card", className)}>{children}</div>;
}

export function Badge({
  children,
  tone = "default",
  className
}: Readonly<{ children: React.ReactNode; tone?: "default" | "success" | "warning" | "danger" | "cyan"; className?: string }>) {
  const tones = {
    default: "border-zinc-700 bg-zinc-950 text-zinc-200",
    success: "border-success/30 bg-success/10 text-success",
    warning: "border-warning/30 bg-warning/10 text-warning",
    danger: "border-danger/30 bg-danger/10 text-danger",
    cyan: "border-zinc-500/40 bg-white/5 text-zinc-100"
  };
  return (
    <span className={clsx("inline-flex max-w-full items-center rounded-md border px-2.5 py-1 text-sm font-medium whitespace-normal break-words", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Button({
  children,
  className,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const variants = {
    primary: "bg-primary text-black hover:bg-zinc-200",
    secondary: "border border-border bg-surface text-zinc-100 hover:bg-zinc-900",
    ghost: "text-slate-300 hover:bg-white/5"
  };
  return (
    <button
      className={clsx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-4 py-2 text-base font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
