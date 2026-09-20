import { useEffect, useState } from "react";

import {
  currentClientConfig,
  onClientConfig,
  type ClientConfig,
} from "../lib/clientConfig";
import { currentTransport, onTransportChange } from "../lib/socket";

/** The server-decided cadences, re-rendering when one of them changes.

The subscription is what makes a change take effect mid-turn. A hook that
merely read the value once would leave a drawer flushing at the old interval
until they stopped drawing and started again — which is exactly the case #446
asks to work, since the only way to judge the value is to watch somebody draw
while it moves. */
export function useClientConfig(): ClientConfig {
  const [config, setConfig] = useState<ClientConfig>(currentClientConfig);
  useEffect(() => onClientConfig(setConfig), []);
  return config;
}

/** The transport this session is on, as a rendering value (#887).

The drawing cadence depends on it: a flush on long-polling is an HTTP POST,
so it goes out a third as often. It changes under a session too - a polling
session is upgraded the moment a WebSocket works - so it is subscribed to
rather than read once.
*/
export function useTransport(): string | null {
  const [transport, setTransport] = useState<string | null>(currentTransport);
  useEffect(() => onTransportChange(setTransport), []);
  return transport;
}
