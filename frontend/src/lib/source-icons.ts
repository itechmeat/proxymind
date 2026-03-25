import {
  FileText,
  FileType,
  Globe,
  Headphones,
  ImageIcon,
  type LucideIcon,
  Video,
} from "lucide-react";

interface SourceIconDefinition {
  color: string;
  Icon: LucideIcon;
}

const DEFAULT_SOURCE_ICON = {
  Icon: FileText,
  color: "#6b7280",
} as const satisfies SourceIconDefinition;

const SOURCE_ICON_MAP: Record<string, SourceIconDefinition> = {
  audio: {
    Icon: Headphones,
    color: "#f59e0b",
  },
  docx: DEFAULT_SOURCE_ICON,
  html: {
    Icon: Globe,
    color: "#3b82f6",
  },
  image: {
    Icon: ImageIcon,
    color: "#10b981",
  },
  markdown: {
    Icon: FileType,
    color: "#6b7280",
  },
  pdf: {
    Icon: FileText,
    color: "#ef4444",
  },
  txt: {
    Icon: FileType,
    color: "#6b7280",
  },
  video: {
    Icon: Video,
    color: "#a855f7",
  },
};

export function getSourceIcon(sourceType: string): SourceIconDefinition {
  return SOURCE_ICON_MAP[sourceType.toLowerCase()] ?? DEFAULT_SOURCE_ICON;
}
