"use client";

import { signIn } from "next-auth/react";
import { Icon } from "./Icon";

export function SignInButton({ className = "btn btn-secondary btn-lg", icon = true, children }: { className?: string; icon?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" className={className} onClick={() => signIn("google", { redirectTo: "/chat" })}>
      {icon && <Icon name="up" />}
      {children}
    </button>
  );
}
