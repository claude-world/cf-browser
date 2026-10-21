/**
 * Every R2 object the Worker reads or writes lives under this prefix.
 * setup.sh installs an eight-day bucket lifecycle rule for exactly this prefix
 * and keeps its root ownership marker (`.cf-browser-managed-v1`) outside it.
 */
export const R2_OBJECT_PREFIX = "cf-browser/";

export function r2ObjectKey(key: string): string {
  return `${R2_OBJECT_PREFIX}${key}`;
}
