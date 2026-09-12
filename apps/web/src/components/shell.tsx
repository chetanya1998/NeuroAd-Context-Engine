"use client";

import { Activity, FileText, Gauge, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

function NeuroAdLogo() {
  return (
    <div className="relative flex h-8 w-8 items-center justify-center rounded-md border border-cyan/30 bg-cyan text-[#061012] shadow-[0_0_18px_rgba(20,201,190,0.16)]">
      <svg viewBox="0 0 44 44" className="h-5 w-5" aria-hidden="true">
        <path
          d="M9 27C14.2 27 17 22 17 15V12L27 32V29C27 22 29.8 17 35 17"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3.4"
        />
        <circle cx="9" cy="27" r="2.2" fill="currentColor" />
        <circle cx="35" cy="17" r="2.2" fill="currentColor" />
      </svg>
    </div>
  );
}

const navItems = [
  { label: "Analyze", icon: Gauge, sectionId: "section-analyze" },
  { label: "Pipeline", icon: Activity, sectionId: "section-pipeline" },
  { label: "Reports", icon: FileText, sectionId: "section-reports" }
];

export function AppShell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const pathname = usePathname();
  const isHome = pathname === "/";
  const isReport = pathname.startsWith("/dashboard") || pathname.startsWith("/reports") || pathname.startsWith("/compare") || pathname.startsWith("/insights");
  const [showHeader, setShowHeader] = useState(true);

  useEffect(() => {
    let lastY = window.scrollY;

    function handleScroll() {
      const currentY = window.scrollY;
      if (currentY < 32) {
        setShowHeader(true);
      } else if (currentY > lastY + 8) {
        setShowHeader(false);
      } else if (currentY < lastY - 8) {
        setShowHeader(true);
      }
      lastY = currentY;
    }

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  function scrollToSection(sectionId: string) {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <main className={`app-shell min-h-screen w-screen overflow-x-clip bg-background text-slate-50 ${className}`}>
      <header
        className={[
          "app-header sticky top-0 z-30 w-screen border-b border-white/[0.06] bg-background/90 backdrop-blur-xl transition-transform duration-300",
          showHeader ? "translate-y-0" : "-translate-y-full"
        ].join(" ")}
      >
        <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 lg:px-6">
          <Link href="/" className="flex items-center gap-2 transition hover:opacity-80">
            <NeuroAdLogo />
            <div className="hidden sm:block">
              <p className="text-[10px] font-bold tracking-tight text-zinc-100">NEUROAD <span className="font-medium text-zinc-500">CONTEXT ENGINE</span></p>
            </div>
          </Link>

          {isHome ? (
            <button
              onClick={() => scrollToSection("input-section")}
              className="inline-flex items-center gap-1.5 rounded-md bg-cyan px-3 py-1.5 text-xs font-bold text-[#061012] transition hover:bg-[#31ded4] md:hidden"
            >
              Upload
              <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          ) : (
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-md bg-cyan px-3 py-1.5 text-xs font-bold text-[#061012] transition hover:bg-[#31ded4] md:hidden"
            >
              Upload
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          )}

          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon;
              return isHome ? (
                <button
                  key={item.label}
                  onClick={() => scrollToSection(item.sectionId)}
                  className="group flex items-center gap-2 rounded-md px-3 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.06] hover:text-white"
                >
                  <Icon className="h-3.5 w-3.5 text-zinc-600 transition group-hover:text-white" />
                  {item.label}
                </button>
              ) : (
                <Link
                  key={item.label}
                  href={`/#${item.sectionId}`}
                  className={`group flex items-center gap-2 rounded-md px-3 py-1.5 text-[11px] font-medium transition hover:bg-white/[0.06] hover:text-white ${item.label === "Reports" && isReport ? "bg-[#272336] text-zinc-100 shadow-[inset_0_-2px_0_#16c7bb]" : "text-zinc-500"}`}
                >
                  <Icon className="h-3.5 w-3.5 text-zinc-600 transition group-hover:text-white" />
                  {item.label}
                </Link>
              );
            })}

            {isHome ? (
              <button
                onClick={() => scrollToSection("input-section")}
                className="ml-3 inline-flex items-center gap-1.5 rounded-md bg-cyan px-3 py-1.5 text-[11px] font-bold text-[#061012] transition hover:bg-[#31ded4]"
              >
                Upload Video
                <ArrowUpRight className="h-3.5 w-3.5" />
              </button>
            ) : (
              <Link
                href="/"
                className="ml-3 inline-flex items-center gap-1.5 rounded-md bg-cyan px-3 py-1.5 text-[11px] font-bold text-[#061012] transition hover:bg-[#31ded4]"
              >
                Upload Video
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </nav>
        </div>
      </header>
      {children}
    </main>
  );
}
