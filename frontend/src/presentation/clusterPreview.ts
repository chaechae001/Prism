import type { Story } from "../api/types";

export function clusterSourceLabel(framing: string): string {
  return framing.replace(/\s*·\s*동일 사건 검토 전/g, "").trim();
}

// The local artifact adapter owns this namespace; detail responses have no feed meta.
export function isLocalClusterStory(story?: Pick<Story, "id">): boolean {
  return /^(local|db)-cluster-[0-9a-f]{24}$/.test(story?.id || "");
}

export function isDbClusterStory(story?: Pick<Story, "id">): boolean {
  return /^db-cluster-[0-9a-f]{24}$/.test(story?.id || "");
}
