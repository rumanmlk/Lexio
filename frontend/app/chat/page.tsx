import type { Metadata } from "next";
import { Workspace } from "@/components/Workspace";

// An app shell with no indexable content; ?q= variants must not compete with the landing page.
export const metadata: Metadata = { title: "Ask", robots: { index: false, follow: false } };

export default function Chat() {
  return <Workspace />;
}
