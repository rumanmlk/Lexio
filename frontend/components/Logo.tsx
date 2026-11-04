import Link from "next/link";
import { LOGO } from "@/lib/logo";

/** The Lexio mark: an L made from a page margin and an amber highlighter stroke. */
export function Mark({ title }: { title?: string }) {
  return (
    <svg viewBox="0 0 32 32" role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true} focusable="false">
      {LOGO.map(({ role, ...r }, i) => (
        <rect key={i} className={`mark-${role}`} {...r} />
      ))}
    </svg>
  );
}

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="logo" aria-label="Lexio home">
      <Mark />
      <span>Lexio</span>
    </Link>
  );
}
