"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession } from "@/lib/session";
import ConnectWallet from "./ConnectWallet";
import { Badge } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", n: "•" },
  { href: "/models/create", label: "1. Create / Upload", n: "1", dev: true },
  { href: "/train", label: "2. Train Model", n: "2", dev: true },
  { href: "/evaluate", label: "3. Evaluate Model", n: "3", dev: true },
  { href: "/package", label: "4. Package Model", n: "4", dev: true },
  { href: "/deploy", label: "5. Deploy Model", n: "5", dev: true },
  { href: "/registry", label: "6. Blockchain Registry", n: "6", dev: true },
  { href: "/marketplace", label: "Marketplace", n: "M" },
  { href: "/security", label: "Security Verification", n: "S" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const { user, ready, logout } = useSession();
  const path = usePathname();
  const router = useRouter();
  const isLogin = path === "/login";

  useEffect(() => {
    if (ready && !user && !isLogin) router.replace("/login");
    if (ready && user && isLogin) router.replace("/");
  }, [ready, user, isLogin, router]);

  if (isLogin) return <>{children}</>;
  if (!ready || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-600">
          <span className="h-2 w-2 animate-ping rounded-full bg-indigo-600"></span>
          Loading session…
        </div>
      </div>
    );
  }

  const items = NAV.filter((n) => !n.dev || user.role === "developer");
  const currentNav = NAV.find((n) => n.href === "/" ? path === "/" : path.startsWith(n.href));

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-800 bg-slate-900 text-slate-200 md:flex">
        <div className="border-b border-slate-800/80 px-6 py-5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white shadow-xs">
              AI
            </div>
            <div>
              <div className="text-base font-bold leading-tight text-white tracking-tight">ML Platform</div>
              <div className="text-[11px] font-medium text-slate-400">Decentralized Registry</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-1.5 px-3 py-4">
          {items.map((n) => {
            const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`group flex items-center justify-between rounded-lg px-3.5 py-2.5 text-sm font-medium transition-all ${
                  active
                    ? "bg-indigo-600 text-white shadow-xs"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white"
                }`}
              >
                <span>{n.label}</span>
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-md text-[11px] font-semibold transition-colors ${
                    active ? "bg-indigo-700 text-indigo-100" : "bg-slate-800 text-slate-400 group-hover:text-slate-200"
                  }`}
                >
                  {n.n}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-slate-800 bg-slate-950/60 p-4">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-white truncate text-sm">{user.username}</div>
            <Badge>{user.role === "developer" ? "approved" : "pending"}</Badge>
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
            <span className="capitalize">{user.role}</span>
            <span className={user.certificate_status?.valid ? "text-emerald-400 font-medium" : "text-rose-400 font-medium"}>
              X.509 {user.certificate_status?.valid ? "Valid" : "Invalid"}
            </span>
          </div>
          <button
            onClick={() => logout()}
            className="mt-3.5 w-full rounded-md border border-slate-700/80 bg-slate-800/80 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-700 hover:text-white"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-8 shadow-2xs">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">ML Lifecycle</span>
            <span className="text-slate-300">/</span>
            <span className="text-sm font-bold text-slate-900">{currentNav?.label || "Overview"}</span>
          </div>
          <div className="flex items-center gap-4">
            <ConnectWallet />
          </div>
        </header>
        <main className="flex-1 space-y-6 p-8 max-w-7xl w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}
