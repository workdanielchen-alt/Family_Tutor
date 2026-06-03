"use client";

import {
  AlertCircle,
  BarChart3,
  ClipboardList,
  History,
  NotebookPen,
  Wand2,
  type LucideIcon,
} from "lucide-react";

export type SpaceItemKey =
  | "dashboard"
  | "chat_history"
  | "notebooks"
  | "question_bank"
  | "wrong_answers"
  | "skills";

export type SpaceMemoryFile = "summary" | "profile";

export interface SpaceItem {
  key: SpaceItemKey;
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const SPACE_ITEMS: SpaceItem[] = [
  {
    key: "dashboard",
    href: "/space",
    label: "Learning Progress",
    description: "Mastery overview, weak points, wrong answers and practice.",
    icon: BarChart3,
  },
  {
    key: "chat_history",
    href: "/space/chat-history",
    label: "Chat History",
    description: "Review and reopen previous conversations.",
    icon: History,
  },
  {
    key: "notebooks",
    href: "/space/notebooks",
    label: "Notebooks",
    description:
      "Organize saved outputs from chat, research, Co-Writer, and more.",
    icon: NotebookPen,
  },
  {
    key: "question_bank",
    href: "/space/questions",
    label: "Question Bank",
    description: "Review and organize quiz questions across sessions.",
    icon: ClipboardList,
  },
  {
    key: "wrong_answers",
    href: "/space/wrong-answers",
    label: "Wrong Answers",
    description: "Review mistakes grouped by knowledge point with practice generation.",
    icon: AlertCircle,
  },
  {
    key: "skills",
    href: "/space/skills",
    label: "Skills",
    description: "Behavior playbooks that guide chat responses.",
    icon: Wand2,
  },
];
