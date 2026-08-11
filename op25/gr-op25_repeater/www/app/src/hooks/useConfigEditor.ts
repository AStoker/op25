/**
 * The editable-configuration client: load, save, roll back, reset, export.
 *
 * Kept out of `op25Service` deliberately. That service is the decoder's *live*
 * state, arriving over the WebSocket at 1 Hz; this is a REST resource that only
 * changes when someone edits it. Folding them together would mean re-rendering
 * the whole app every second because of a config panel nobody has open.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl } from '../utils/url';
import type {
  ConfigSaveResult,
  ConfigSchema,
  ConfigState,
  ConfigVersion,
} from '../types/config';

/** A write that failed, with whatever the server was able to explain. */
export interface ConfigError {
  message: string;
  detail?: string;
  /** Field-level complaints from `_validate_config`, when it rejected the body. */
  problems?: string[];
  status?: number;
}

/** Statuses a proxy invents when it cannot reach the thing behind it. */
const GATEWAY_STATUSES = new Set([502, 503, 504]);

/** Whether the body is JSON this app wrote, as opposed to a proxy's error page.
 *  Reads a clone, so the response is still intact for `readError`. */
async function hasJsonBody(resp: Response): Promise<boolean> {
  try {
    const body: unknown = await resp.clone().json();
    return Boolean(body && typeof body === 'object' && 'error' in body);
  } catch {
    return false;
  }
}

async function readError(resp: Response): Promise<ConfigError> {
  let body: Record<string, unknown> = {};
  try {
    body = await resp.json();
  } catch {
    /* a proxy error page, or an empty body */
  }
  return {
    message: String(body.error ?? `HTTP ${resp.status}`),
    detail: body.detail ? String(body.detail) : undefined,
    problems: Array.isArray(body.problems) ? body.problems.map(String) : undefined,
    status: resp.status,
  };
}

export interface UseConfigEditor {
  schema: ConfigSchema | null;
  state: ConfigState | null;
  history: ConfigVersion[];
  loading: boolean;
  /** Failure of the last load or mutation. Cleared when the next one starts. */
  error: ConfigError | null;
  /** Result of the last successful save — carries `needs_restart`. */
  lastSave: ConfigSaveResult | null;
  busy: boolean;
  reload: () => Promise<void>;
  save: (config: Record<string, unknown>, summary?: string, source?: string)
    => Promise<ConfigSaveResult | null>;
  rollback: (versionId: number) => Promise<ConfigSaveResult | null>;
  resetToPreset: () => Promise<ConfigSaveResult | null>;
  exportConfig: (path: string) => Promise<string | null>;
  /** Ask Supervisor to restart the add-on so restart-required fields take effect. */
  restartAddon: () => Promise<boolean>;
  dismissSave: () => void;
}

export function useConfigEditor(active: boolean): UseConfigEditor {
  const [schema, setSchema] = useState<ConfigSchema | null>(null);
  const [state, setState] = useState<ConfigState | null>(null);
  const [history, setHistory] = useState<ConfigVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ConfigError | null>(null);
  const [lastSave, setLastSave] = useState<ConfigSaveResult | null>(null);

  // A reload racing a save would show pre-save values as if the save had not
  // happened; the counter lets a stale response be discarded.
  const loadSeq = useRef(0);

  const reload = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const [schemaResp, stateResp, historyResp] = await Promise.all([
        fetch(apiUrl('api/config/schema')),
        fetch(apiUrl('api/config/state')),
        fetch(apiUrl('api/config/history')),
      ]);
      if (seq !== loadSeq.current) return;

      if (!stateResp.ok) {
        setError(await readError(stateResp));
        setState(null);
      } else {
        setState(await stateResp.json());
      }
      if (schemaResp.ok) setSchema(await schemaResp.json());
      // History is the one part that is allowed to be missing: a save works
      // without a database, so an editor that refused to render without one
      // would be wrong.
      setHistory(historyResp.ok ? (await historyResp.json()).versions ?? [] : []);
    } catch (e) {
      if (seq === loadSeq.current) {
        setError({ message: e instanceof Error ? e.message : 'network error' });
      }
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => { if (active) void reload(); }, [active, reload]);

  /** Run a mutation, then reload so the panel reflects what the server stored. */
  const mutate = useCallback(async (
    request: () => Promise<Response>,
  ): Promise<ConfigSaveResult | null> => {
    setBusy(true);
    setError(null);
    try {
      const resp = await request();
      if (!resp.ok) {
        setError(await readError(resp));
        return null;
      }
      const result: ConfigSaveResult = await resp.json();
      setLastSave(result);
      await reload();
      return result;
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : 'network error' });
      return null;
    } finally {
      setBusy(false);
    }
  }, [reload]);

  const save = useCallback((
    config: Record<string, unknown>,
    summary?: string,
    source = 'gui',
  ) => mutate(() => fetch(apiUrl('api/config'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, summary, source }),
  })), [mutate]);

  const rollback = useCallback((versionId: number) => mutate(
    () => fetch(apiUrl(`api/config/rollback/${versionId}`), { method: 'POST' }),
  ), [mutate]);

  const resetToPreset = useCallback(() => mutate(
    () => fetch(apiUrl('api/config/reset'), { method: 'POST' }),
  ), [mutate]);

  const exportConfig = useCallback(async (path: string): Promise<string | null> => {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(apiUrl('api/config/export'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!resp.ok) {
        setError(await readError(resp));
        return null;
      }
      return String((await resp.json()).path ?? path);
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : 'network error' });
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const restartAddon = useCallback(async (): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(apiUrl('api/restart'), { method: 'POST' });
      // A gateway status is not an answer from the server — it is the *proxy*
      // saying it has no server to ask, which is exactly what a container being
      // restarted looks like from Home Assistant's ingress. Reporting it as a
      // failed restart is the worst reading available: the restart is underway,
      // and the user's response to being told it failed is to do it again.
      // Anything the decoder itself refuses (403, 501, and the 502 it raises
      // when Supervisor says no) carries a JSON body and is reported.
      if (!resp.ok) {
        if (GATEWAY_STATUSES.has(resp.status) && !(await hasJsonBody(resp))) return true;
        setError(await readError(resp));
        return false;
      }
      return true;
    } catch {
      // The container going away mid-request is the success case, so a network
      // error here is not reported as a failure.
      return true;
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    schema, state, history, loading, error, lastSave, busy,
    reload, save, rollback, resetToPreset, exportConfig, restartAddon,
    dismissSave: useCallback(() => setLastSave(null), []),
  };
}

// ---------------------------------------------------------------------------
// Path helpers
//
// The server flattens config paths as `devices[sdr0].gains`. The editor needs to
// read and write those against a nested object, and a device may be named
// anything -- including with a dot in it -- so splitting on '.' is not safe.
// ---------------------------------------------------------------------------

/** Split a flattened path into segments, ignoring dots inside brackets. */
export function splitPath(path: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = '';
  for (const ch of path) {
    if (ch === '[') depth += 1;
    else if (ch === ']') depth = Math.max(0, depth - 1);
    if (ch === '.' && depth === 0) {
      parts.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  parts.push(current);
  return parts;
}

/** Resolve a pattern like `devices[*].gains` against a concrete element key. */
export function concretePath(pattern: string, key: string | number): string {
  return pattern.replace('[*]', `[${key}]`);
}

/** The final segment of a path, which is the object key to read or write. */
export function leafKey(path: string): string {
  const parts = splitPath(path);
  const last = parts[parts.length - 1];
  return last.replace(/\[[^\]]*\]$/, '');
}

/** Read `devices[sdr0].gains` out of a nested config. */
export function readPath(config: unknown, path: string): unknown {
  let node: unknown = config;
  for (const raw of splitPath(path)) {
    if (node === null || node === undefined) return undefined;
    const match = /^([^[]*)(?:\[(.*)\])?$/.exec(raw);
    if (!match) return undefined;
    const [, key, index] = match;
    if (key) {
      if (typeof node !== 'object') return undefined;
      node = (node as Record<string, unknown>)[key];
    }
    if (index !== undefined) {
      if (!Array.isArray(node)) return undefined;
      node = node.find((item) => item && typeof item === 'object'
        && ['name', 'sysname', 'instance_name'].some(
          (id) => String((item as Record<string, unknown>)[id]) === index));
    }
  }
  return node;
}

/**
 * Write a value at a flattened path, returning a new config.
 *
 * Structural sharing is not attempted: these objects are small and a config save
 * is a human-paced action, so a plain deep clone is easier to be sure of than a
 * partial copy that might alias the caller's state.
 */
export function writePath(
  config: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const next = structuredClone(config);
  const parts = splitPath(path);
  let node: unknown = next;

  for (let i = 0; i < parts.length; i += 1) {
    const match = /^([^[]*)(?:\[(.*)\])?$/.exec(parts[i]);
    if (!match) return next;
    const [, key, index] = match;
    const isLast = i === parts.length - 1;

    if (isLast && index === undefined) {
      if (node && typeof node === 'object') {
        (node as Record<string, unknown>)[key] = value;
      }
      return next;
    }

    if (key) {
      if (!node || typeof node !== 'object') return next;
      const holder = node as Record<string, unknown>;
      if (holder[key] === undefined) holder[key] = index !== undefined ? [] : {};
      node = holder[key];
    }
    if (index !== undefined) {
      if (!Array.isArray(node)) return next;
      const found = node.find((item) => item && typeof item === 'object'
        && ['name', 'sysname', 'instance_name'].some(
          (id) => String((item as Record<string, unknown>)[id]) === index));
      if (found === undefined) return next;
      node = found;
    }
  }
  return next;
}

/** Element identities for a section's list, e.g. every `devices[].name`. */
export function listKeys(
  config: Record<string, unknown>,
  listPath: string | undefined,
  identity = 'name',
): string[] {
  if (!listPath) return [];
  const list = readPath(config, listPath);
  if (!Array.isArray(list)) return [];
  return list
    .map((item) => (item && typeof item === 'object'
      ? (item as Record<string, unknown>)[identity]
      : undefined))
    .filter((v): v is string | number => v !== undefined && v !== null)
    .map(String);
}
