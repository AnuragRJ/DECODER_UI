/**
 * UI-side log normalization: strip ANSI terminal escape sequences before
 * display in the center execution log.
 *
 * Covers CSI/SGR color codes (e.g. "\x1b[32m", "\x1b[0m", "\x1b[36m"),
 * OSC sequences (e.g. "\x1b]0;title\x07") and two-byte control sequences.
 *
 * The backend's original structured payload is preserved untouched in the
 * store and in the Technical Event Inspector ("View technical details");
 * this helper is applied only at render time so the visible log stays clean
 * and readable without altering backend log meaning.
 */
const ANSI_ESCAPE_RE =
  /\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])/g;

export function stripAnsi(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "string" ? value : String(value);
  if (!text.includes("\x1b")) return text;
  return text.replace(ANSI_ESCAPE_RE, "");
}
