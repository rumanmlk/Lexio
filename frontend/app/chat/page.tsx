import type { Metadata } from "next";
import { Workspace } from "@/components/Workspace";

export const metadata: Metadata = { title: "Ask" };

export default function Chat() {
  return <Workspace />;
}
