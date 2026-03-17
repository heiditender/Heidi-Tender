import type { Metadata } from "next";
import { TaskConsolePage } from "@/components/task-console-page";

export const metadata: Metadata = {
  title: "Task Console",
  description: "Create jobs, upload tender files, and run the Heidi Tender matching workflow.",
};

export default function ConsolePage() {
  return <TaskConsolePage />;
}
