"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export type NavIcon = "queue" | "matches" | "reports" | "help" | "imports" | "rules" | "sources" | "settings";
export type NavLink = { href: string; label: string; icon: NavIcon };

const PATHS: Record<NavIcon, ReactNode> = {
  queue: <path d="M4 6h16M4 12h16M4 18h10" />,
  matches: (
    <>
      <path d="M9 12l2 2 4-4" />
      <rect x="3" y="3" width="18" height="18" rx="3" />
    </>
  ),
  reports: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 114 2c-.8.5-1.5 1-1.5 2v.5" />
      <path d="M12 17h.01" />
    </>
  ),
  imports: <path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />,
  rules: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
    </>
  ),
  sources: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" />
    </>
  ),
};

function Icon({ name }: { name: NavIcon }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="size-5 shrink-0">
      {PATHS[name]}
    </svg>
  );
}

function Group({ title, links }: { title?: string; links: NavLink[] }) {
  const pathname = usePathname();
  return (
    <div className="flex flex-col gap-1">
      {title ? (
        <span className="hidden px-3 pt-4 pb-1 text-[11px] font-semibold tracking-wide text-indigo-300/70 md:block">{title}</span>
      ) : (
        <span aria-hidden className="mx-3 mt-3 mb-1 hidden border-t border-white/10 md:block" />
      )}
      <ul className="flex flex-wrap gap-1 md:flex-col">
        {links.map((l) => {
          const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
          return (
            <li key={l.href}>
              <Link
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  active ? "bg-white/12 text-white shadow-inner" : "text-indigo-100/75 hover:bg-white/6 hover:text-white"
                }`}
              >
                <Icon name={l.icon} />
                {l.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function NavLinks({ expert, admin, help }: { expert: NavLink[]; admin: NavLink[]; help: NavLink[] }) {
  return (
    <div className="flex flex-wrap gap-x-2 md:flex-col">
      <Group title="کار روزانه" links={expert} />
      {admin.length > 0 && <Group title="مدیریت" links={admin} />}
      <Group links={help} />
    </div>
  );
}
