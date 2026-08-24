/** Copy text via the async clipboard API. Returns false instead of throwing
 * when the API is unavailable (insecure context, older browser) or refuses,
 * so callers can show their own fallback guidance. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
