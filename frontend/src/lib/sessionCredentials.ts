type ReadableStorage = Pick<Storage, "getItem" | "removeItem">;
type WritableStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const reconnectKey = (code: string) => `sketchy_reconnect_secret_${code}`;
const legacyTokenKey = (code: string) => `sketchy_token_${code}`;

export function readReconnectSecret(storage: ReadableStorage, code: string): string | null {
  const legacyKey = legacyTokenKey(code);
  if (storage.getItem(legacyKey) !== null) {
    // Legacy values were broadcastable player IDs, so they are not credentials.
    storage.removeItem(legacyKey);
  }
  return storage.getItem(reconnectKey(code));
}

export function writeReconnectSecret(
  storage: WritableStorage,
  code: string,
  reconnectSecret: string,
): void {
  storage.setItem(reconnectKey(code), reconnectSecret);
  storage.removeItem(legacyTokenKey(code));
}

export function clearReconnectSecret(storage: ReadableStorage, code: string): void {
  storage.removeItem(reconnectKey(code));
  storage.removeItem(legacyTokenKey(code));
}
