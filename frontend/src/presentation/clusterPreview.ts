import type { Story } from "../api/types";

// The local artifact adapter owns this namespace; detail responses have no feed meta.
export function isLocalClusterStory(story?: Pick<Story, "id">): boolean {
  return /^(local|db)-cluster-[0-9a-f]{24}$/.test(story?.id || "");
}

export function isDbClusterStory(story?: Pick<Story, "id">): boolean {
  return /^db-cluster-[0-9a-f]{24}$/.test(story?.id || "");
}
