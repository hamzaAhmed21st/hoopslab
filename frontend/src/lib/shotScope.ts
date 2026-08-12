import type { ShotPage } from "../api/types";

export function pageScope(page: ShotPage): string {
  const { offset, total } = page.pagination;
  if (page.items.length === 0) {
    return `Showing newest 0 of ${total.toLocaleString("en-US")} attempts`;
  }
  return `Showing newest ${offset + 1}–${Math.min(
    offset + page.items.length,
    total,
  )} of ${total.toLocaleString("en-US")} attempts`;
}
