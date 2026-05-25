import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { ThemeProvider, CssBaseline, Box, Container } from '@mui/material';
import { buildTheme } from './theme';
import { useAudio } from './hooks/useAudio';
import { useControl } from './hooks/useControl';
import type {
  Settings,
  SmartColor,
  ChannelData,
  NacData,
  CallHistoryEntry,
  TgCacheEntry,
  SiteAliases,
  Preset,
  ServerResponse,
  TerminalConfigResponse,
  ChannelUpdateResponse,
  TrunkUpdateResponse,
  ChangeFreqResponse,
  RxUpdateResponse,
  WsInstancesResponse,
  CallLogResponse,
  FullConfigResponse,
  WuidEntry,
  PlotResponse,
} from './types';

// Components
import NavBar from './components/NavBar';
import MainDisplay from './components/MainDisplay';
import ChannelControls from './components/ChannelControls';
import TalkgroupPanel from './components/TalkgroupPanel';
import FrequencyTable from './components/FrequencyTable';
import ChannelTable from './components/ChannelTable';
import CallHistory from './components/CallHistory';
import SubscriberTable from './components/SubscriberTable';
import SettingsDialog from './components/SettingsDialog';
import ConfigDialog from './components/ConfigDialog';
import AboutDialog from './components/AboutDialog';
import PlotPanel from './components/PlotPanel';

// ── Constants ────────────────────────────────────────────────────────────────
const MAX_HISTORY_ROWS = 1000;
const MAX_HISTORY_SECONDS = 5;
const MAX_TG_CHARS = 20;

// ── Default settings ─────────────────────────────────────────────────────────
const DEFAULT_SETTINGS: Settings = {
  smartColors: true,
  showBandPlan: true,
  showAdjacentSites: true,
  showChannelsTable: true,
  showCallHistory: true,
  trackSubscribers: true,
  subscriberMode: 'all',
  callHistorySource: 'frequency',
  muteAudioAtStartup: false,
  accentColor: '#00ffff',
  callHistoryMaxRows: 500,
  radioIdInFreqTable: false,
  serverUrl: '',
};

const DEFAULT_SMART_COLORS: SmartColor[] = [
  { keywords: ['fire', 'fd'], color: '#ff5c5c' },
  { keywords: ['pd', 'police', 'sheriff', 'so'], color: '#66aaff' },
  { keywords: ['ems', 'med', 'amr', 'ambulance'], color: '#ffb84d' },
];

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem('op25-react-settings');
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return DEFAULT_SETTINGS;
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function cleanStr(v: unknown): string {
  if (v == null) return '';
  return String(v).trim();
}

function hasValue(v: unknown): boolean {
  return cleanStr(v).length > 0;
}

function sysHex3(sysid: unknown): string {
  const n = Number(sysid);
  if (!Number.isFinite(n)) return cleanStr(sysid).toUpperCase();
  return n.toString(16).toUpperCase().padStart(3, '0');
}

function epochToTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}

function buildSiteAliases(
  chans: FullConfigResponse['trunking'] extends undefined ? never : NonNullable<FullConfigResponse['trunking']>['chans'],
): SiteAliases {
  const result: SiteAliases = {};
  if (!Array.isArray(chans)) return result;
  for (const sys of chans) {
    if (!sys?.sysname || !sys.site_alias) continue;
    const key = String(sys.sysname).trim().toUpperCase();
    result[key] = sys.site_alias as unknown as SiteAliases[string];
  }
  return result;
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  // ── Settings ─────────────────────────────────────────────────────────────
  const [settings, setSettings] = useState<Settings>(loadSettings);

  const saveAllSettings = useCallback((newSettings: Settings) => {
    setSettings(newSettings);
    localStorage.setItem('op25-react-settings', JSON.stringify(newSettings));
  }, []);

  // ── Theme (rebuilds when accent changes) ─────────────────────────────────
  const theme = useMemo(() => buildTheme(settings.accentColor), [settings.accentColor]);

  // ── Control transport (WS + HTTP fallback) ─────────────────────────────────
  // Defined after response handlers are declared; sendCommand is exposed via ref
  // so the polling interval closure always has the latest version.
  const dispatchResponsesRef = useRef<(r: ServerResponse[]) => void>(() => {});
  const dispatchResponses    = useCallback((r: ServerResponse[]) => dispatchResponsesRef.current(r), []);

  // ── Channel management ───────────────────────────────────────────────────
  const [channelList, setChannelList] = useState<number[]>([]);
  const [channelIndex, setChannelIndex] = useState(0);

  // Stable refs so the polling timer never goes stale
  const channelListRef = useRef<number[]>([]);
  const channelIndexRef = useRef(0);
  channelListRef.current = channelList;
  channelIndexRef.current = channelIndex;

  // ── Current activity (from change_freq + trunk_update) ───────────────────
  const [currentFreq, setCurrentFreq] = useState(0);
  const [currentSystem, setCurrentSystem] = useState('');
  const [currentTgid, setCurrentTgid] = useState<number | null>(null);
  const [currentTag, setCurrentTag] = useState('');
  const [currentStreamUrl, setCurrentStreamUrl] = useState<string | null>(null);
  const [currentNac, setCurrentNac] = useState<number | null>(null);
  const [currentSrcAddr, setCurrentSrcAddr] = useState(0);
  const [currentEncrypted, setCurrentEncrypted] = useState(0);
  const [currentEmergency, setCurrentEmergency] = useState(0);
  const [captureActive, setCaptureActive] = useState(false);
  const [errorVal, setErrorVal] = useState<number | null>(null);

  // ── Config from server ───────────────────────────────────────────────────
  const [smartColors, setSmartColors] = useState<SmartColor[]>(DEFAULT_SMART_COLORS);
  const [tuningStepLarge, setTuningStepLarge] = useState(1200);
  const [tuningStepSmall, setTuningStepSmall] = useState(100);
  const [defaultChannel, setDefaultChannel] = useState<number | null>(null);

  // ── Channel table data ────────────────────────────────────────────────────
  const [channels, setChannels] = useState<ChannelData[]>([]);

  // ── System / frequency data ──────────────────────────────────────────────
  const [nacData, setNacData] = useState<Record<string, NacData>>({});
  const [siteAliases, setSiteAliases] = useState<SiteAliases>({});

  // ── Subscriber data ───────────────────────────────────────────────────────
  const [subscriberData, setSubscriberData] = useState<Record<string, WuidEntry>>({});

  // ── Call history ──────────────────────────────────────────────────────────
  const [callHistory, setCallHistory] = useState<CallHistoryEntry[]>([]);
  const callHistorySeenRef = useRef<Map<string, number>>(new Map());

  // ── TG tag cache ──────────────────────────────────────────────────────────
  const tgTagCacheRef = useRef<Record<string, Record<string, TgCacheEntry>>>({});

  // ── WebSocket audio endpoints ─────────────────────────────────────────────
  const [wsEndpoints, setWsEndpoints] = useState<Record<string, string | null>>({});

  // ── Full config + presets ─────────────────────────────────────────────────
  const [fullConfig, setFullConfig] = useState<FullConfigResponse | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);

  // ── Signal plots (keyed by "chan:mode") ────────────────────────────────────
  const [plots, setPlots] = useState<Record<string, PlotResponse>>({});

  // ── Dialogs ───────────────────────────────────────────────────────────────
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);

  // ── Audio ─────────────────────────────────────────────────────────────────
  const { playingChannels, toggleAudio, initAudioCtx } = useAudio(
    wsEndpoints,
    settings.muteAudioAtStartup,
    settings.serverUrl,
  );

  // Stable ref so the polling interval always calls the latest sendCommand
  const sendCommandRef = useRef<(command: string, arg1?: number, arg2?: number) => void>(() => {});

  // ── TG tag cache helpers ──────────────────────────────────────────────────
  const rememberTag = useCallback((sysidHex: string, tgid: string, tagFromServer: unknown) => {
    if (!hasValue(sysidHex) || !hasValue(tgid)) return;
    const sys = sysidHex.toUpperCase();
    const tg = String(tgid);
    if (!tgTagCacheRef.current[sys]) tgTagCacheRef.current[sys] = {};
    if (!tgTagCacheRef.current[sys][tg]) {
      tgTagCacheRef.current[sys][tg] = { tag: '', hits: 0 };
    }
    tgTagCacheRef.current[sys][tg].hits++;
    const t = cleanStr(tagFromServer);
    if (t && !/^Talkgroup\s+\d+$/i.test(t)) {
      tgTagCacheRef.current[sys][tg].tag = t;
    }
  }, []);

  const bestTag = useCallback(
    (sysidHex: string, tgid: string, tagFromServer: unknown, fallback: string): string => {
      const srv = cleanStr(tagFromServer);
      if (srv) return srv;
      const cached = tgTagCacheRef.current[sysidHex]?.[tgid];
      if (cached?.tag) return cached.tag;
      return fallback;
    },
    [],
  );

  // ── Call history helpers ──────────────────────────────────────────────────
  const appendCallHistory = useCallback(
    (
      sysid: unknown,
      tg1: unknown,
      tg2: unknown,
      tag1: string,
      tag2: string,
      freq: string,
      src1: string,
      src2: string,
      dataSource: string,
    ) => {
      if (dataSource !== settings.callHistorySource) return;

      const now = Date.now();
      const epochMs = now;
      const timestamp = new Date(now).toTimeString().split(' ')[0];
      const sysNum = Number(sysid);
      const sysHex =
        !isNaN(sysNum) && sysid !== null && sysid !== ''
          ? sysNum.toString(16).toUpperCase().padStart(3, '0')
          : '-';

      const makeKey = (tg: string, src: string) => `${sysHex}|${freq}|${tg}|${src}`;

      const isDuplicate = (tg: string, src: string) => {
        const key = makeKey(tg, src);
        const last = callHistorySeenRef.current.get(key);
        if (!last) return false;
        return epochMs - last <= MAX_HISTORY_SECONDS * 1000;
      };

      const markSeen = (tg: string, src: string) => {
        callHistorySeenRef.current.set(makeKey(tg, src), epochMs);
      };

      const newRows: CallHistoryEntry[] = [];

      const processLeg = (tg: unknown, tag: string, src: string) => {
        const tgStr = cleanStr(tg);
        const srcStr = cleanStr(src);
        if (!hasValue(tgStr) || !hasValue(srcStr)) return;
        if (isDuplicate(tgStr, srcStr)) return;
        const tgName = hasValue(tag) ? tag : `Talkgroup ${tgStr}`;
        newRows.push({ timestamp, epochMs, sysHex, freq, tgid: tgStr, tgName, source: srcStr });
        markSeen(tgStr, srcStr);
      };

      processLeg(tg1, tag1, src1);
      processLeg(tg2, tag2, src2);

      if (newRows.length === 0) return;

      setCallHistory((prev) => {
        const combined = [...newRows, ...prev];
        return combined.slice(0, MAX_HISTORY_ROWS);
      });
    },
    [settings.callHistorySource],
  );

  // ── Response handlers ─────────────────────────────────────────────────────
  const handleTerminalConfig = useCallback((d: TerminalConfigResponse) => {
    if (d.smart_colors !== undefined) setSmartColors(d.smart_colors);
    if (d.tuning_step_large !== undefined) setTuningStepLarge(d.tuning_step_large);
    if (d.tuning_step_small !== undefined) setTuningStepSmall(d.tuning_step_small);
    if (d.default_channel !== undefined) setDefaultChannel(d.default_channel);
  }, []);

  const handleChannelUpdate = useCallback(
    (d: ChannelUpdateResponse) => {
      const chList = d.channels.map((c) => c.index);
      setChannelList(chList);
      setChannels(d.channels);

      // Find currently viewed channel info
      const currentCh = chList[channelIndexRef.current];
      const chData = d.channels.find((c) => c.index === currentCh);
      if (chData) {
        if (chData.capture !== undefined) setCaptureActive(chData.capture);
        if (chData.error !== undefined) setErrorVal(chData.error);
      }

      // Sync channel index for default_channel on first load
      if (defaultChannel !== null && chList.length > 0) {
        const idx = chList.indexOf(defaultChannel);
        if (idx >= 0) setChannelIndex(idx);
      }
    },
    [defaultChannel],
  );

  const handleTrunkUpdate = useCallback(
    (d: TrunkUpdateResponse) => {
      if (d.nac !== undefined) setCurrentNac(d.nac);
      if (d.srcaddr !== undefined) setCurrentSrcAddr(d.srcaddr as number);
      if (d.encrypted !== undefined) setCurrentEncrypted(d.encrypted as number);
      if (d.emergency !== undefined) setCurrentEmergency(d.emergency as number);

      // Find matching NAC data
      const newNacData: Record<string, NacData> = {};
      for (const key of Object.keys(d)) {
        if (!/^\d/.test(key)) continue;
        const nac = d[key] as NacData;
        if (!nac || typeof nac !== 'object') continue;

        // Filter to system matching current channel, but only once a system has
        // been identified.  Before the first change_freq is received currentSystem
        // is '' and no NAC data would otherwise be shown.
        if (currentSystem && nac.system !== undefined && nac.system !== currentSystem) continue;

        newNacData[key] = nac;

        // Update subscriber data
        if (nac.wuid_data) {
          setSubscriberData((prev) => ({ ...prev, ...nac.wuid_data }));
        }

        // Populate TG tag cache from frequency data
        const sysidHex = sysHex3(nac.sysid);
        for (const entry of Object.values(nac.frequency_data ?? {})) {
          const [tg1, tg2] = entry.tgids;
          const [tag1, tag2] = entry.tags;
          if (hasValue(tg1)) rememberTag(sysidHex, String(tg1), tag1);
          if (hasValue(tg2)) rememberTag(sysidHex, String(tg2), tag2);
        }

        // Call history from frequency data
        for (const [freq, entry] of Object.entries(nac.frequency_data ?? {})) {
          const [tg1, tg2] = entry.tgids;
          const [tag1Raw, tag2Raw] = entry.tags;
          const [src1Raw, src2Raw] = entry.srctags;
          const [addr1, addr2] = entry.srcaddrs;

          const sysHex = sysHex3(nac.sysid);
          const tag1 = hasValue(tg1) ? bestTag(sysHex, String(tg1), tag1Raw, `Talkgroup ${tg1}`) : '';
          const tag2 = hasValue(tg2) ? bestTag(sysHex, String(tg2), tag2Raw, `Talkgroup ${tg2}`) : '';
          const src1 = hasValue(src1Raw) ? String(src1Raw) : hasValue(addr1) ? `ID: ${addr1}` : '-';
          const src2 = hasValue(src2Raw) ? String(src2Raw) : hasValue(addr2) ? `ID: ${addr2}` : `ID: ${addr1}`;

          const freqMhz = (parseInt(freq) / 1e6).toFixed(6);
          appendCallHistory(nac.sysid, tg1, tg2, tag1, tag2, freqMhz, src1, src2, 'frequency');
        }
      }

      setNacData(newNacData);
    },
    [currentSystem, rememberTag, bestTag, appendCallHistory],
  );

  const handleChangeFreq = useCallback((d: ChangeFreqResponse) => {
    setCurrentFreq(d.freq);
    setCurrentSystem(d.system);
    setCurrentTgid(d.tgid ?? null);
    setCurrentTag(d.tag ?? '');
    setCurrentStreamUrl(d.stream_url ?? null);
    if (d.nac !== undefined) setCurrentNac(d.nac);
  }, []);

  const handleRxUpdate = useCallback((d: RxUpdateResponse) => {
    if (d.error !== undefined) setErrorVal(d.error);
  }, []);

  const handleWsInstances = useCallback((d: WsInstancesResponse) => {
    const next: Record<string, string | null> = {};
    for (const [k, v] of Object.entries(d)) {
      if (k === 'json_type') continue;
      next[k] = v as string | null;
    }
    setWsEndpoints((prev) => ({ ...prev, ...next }));
  }, []);

  const handleCallLog = useCallback(
    (d: CallLogResponse) => {
      if (settings.callHistorySource !== 'voice') return;
      if (!d.log?.length) return;

      const newRows: CallHistoryEntry[] = d.log.map((log) => {
        const dt = new Date(log.time * 1000);
        const ts = [dt.getHours(), dt.getMinutes(), dt.getSeconds()]
          .map((n) => String(n).padStart(2, '0'))
          .join(':');
        const sysHex = (log.sysid ?? 0).toString(16).toUpperCase().padStart(3, '0');
        const freq = (log.freq / 1e6).toFixed(6);
        const tgName = log.tgtag || `Talkgroup ${log.tgid}`;
        const source = log.rtag || (log.rid ? `ID: ${log.rid}` : '-');
        return {
          timestamp: ts,
          epochMs: log.time * 1000,
          sysHex,
          freq,
          tgid: String(log.tgid),
          tgName,
          source,
        };
      });

      setCallHistory((prev) => [...newRows, ...prev].slice(0, MAX_HISTORY_ROWS));
    },
    [settings.callHistorySource],
  );

  const handlePlot = useCallback((d: PlotResponse) => {
    setPlots((prev) => ({ ...prev, [`${d.chan}:${d.mode}`]: d }));
  }, []);

  const handleFullConfig = useCallback((d: FullConfigResponse) => {
    setFullConfig(d);
    const chans = d.trunking?.chans ?? [];
    setSiteAliases(buildSiteAliases(chans));
    // Find presets for current system
    for (const chan of chans) {
      if (chan.presets?.length) {
        setPresets(chan.presets);
        break;
      }
    }
  }, []);

  // ── Master response dispatcher ────────────────────────────────────────────
  dispatchResponsesRef.current = useCallback(
    (responses: ServerResponse[]) => {
      for (const r of responses) {
        if (!('json_type' in r)) continue;
        switch (r.json_type) {
          case 'terminal_config': handleTerminalConfig(r); break;
          case 'channel_update': handleChannelUpdate(r); break;
          case 'trunk_update': handleTrunkUpdate(r); break;
          case 'change_freq': handleChangeFreq(r); break;
          case 'rx_update': handleRxUpdate(r); break;
          case 'ws_instances': handleWsInstances(r); break;
          case 'call_log': handleCallLog(r); break;
          case 'full_config': handleFullConfig(r); break;
          case 'plot': handlePlot(r); break;
        }
      }
    },
    [
      handleTerminalConfig, handleChannelUpdate, handleTrunkUpdate,
      handleChangeFreq, handleRxUpdate, handleWsInstances,
      handleCallLog, handleFullConfig, handlePlot,
    ],
  );

  // ── Wire up useControl (below response handlers so dispatchResponses is stable) ──
  const {
    sendCommand,
    wsConnected,
    connectionError,
    stats: controlStats,
  } = useControl(settings.serverUrl, dispatchResponses);
  sendCommandRef.current = sendCommand;

  // ── Periodic update tick ────────────────────────────────────────────────────
  // Sends the `update` command every second so the server generates fresh data.
  // All other commands are sent immediately through sendCommandRef.
  useEffect(() => {
    sendCommandRef.current('get_terminal_config', 0, 0);
    sendCommandRef.current('get_full_config', 0, 0);
    sendCommandRef.current('get_ws_instances', 0, 0);

    const id = setInterval(() => {
      const list = channelListRef.current;
      const idx  = channelIndexRef.current;
      const ch   = list.length > 0 ? list[idx] : 0;
      sendCommandRef.current('update', 0, ch);
      if (smartColors.length === 0) {
        sendCommandRef.current('get_terminal_config', 0, 0);
      }
    }, 1000);

    return () => clearInterval(id);
  }, []); // Only run once; refs stay current

  // ── Action helpers ────────────────────────────────────────────────────────
  const currentChannelArg = useCallback(() => {
    const list = channelList;
    return list.length > 0 ? list[channelIndex] : 0;
  }, [channelList, channelIndex]);

  const holdTalkgroup = useCallback(
    (tgid: number) => {
      const ch = currentChannelArg();
      if (tgid !== 0) sendCommand('whitelist', tgid, ch);
      sendCommand('hold', tgid, ch);
    },
    [currentChannelArg, sendCommand],
  );

  const scanTalkgroup = useCallback(() => {
    sendCommand('skip', 0, currentChannelArg());
  }, [currentChannelArg, sendCommand]);

  const lockoutTalkgroup = useCallback(
    (tgid?: number) => {
      const id = tgid ?? currentTgid ?? 0;
      if (!id) return;
      sendCommand('lockout', id, currentChannelArg());
    },
    [currentTgid, currentChannelArg, sendCommand],
  );

  const whitelistTalkgroup = useCallback(
    (tgid?: number) => {
      const id = tgid ?? 0;
      if (!id) return;
      sendCommand('whitelist', id, currentChannelArg());
    },
    [currentChannelArg, sendCommand],
  );

  const adjustTune = useCallback(
    (direction: 'ld' | 'sd' | 'su' | 'lu') => {
      const steps: Record<string, number> = {
        ld: -tuningStepLarge,
        sd: -tuningStepSmall,
        su: tuningStepSmall,
        lu: tuningStepLarge,
      };
      sendCommand('adj_tune', steps[direction], currentChannelArg());
    },
    [tuningStepLarge, tuningStepSmall, currentChannelArg, sendCommand],
  );

  const prevChannel = useCallback(() => {
    setChannelIndex((i) => (i <= 0 ? channelList.length - 1 : i - 1));
  }, [channelList.length]);

  const nextChannel = useCallback(() => {
    setChannelIndex((i) => (i >= channelList.length - 1 ? 0 : i + 1));
  }, [channelList.length]);

  const toggleCapture = useCallback(() => {
    sendCommand('capture', 0, currentChannelArg());
  }, [currentChannelArg, sendCommand]);

  const togglePlot = useCallback(
    (plotType: string) => {
      sendCommand('toggle_plot', plotType as unknown as number, currentChannelArg());
    },
    [currentChannelArg, sendCommand],
  );

  const dumpTgids = useCallback(() => {
    sendCommand('dump_tgids', 0, currentChannelArg());
    sendCommand('dump_tracking', 0, currentChannelArg());
  }, [currentChannelArg, sendCommand]);

  const dumpBuffer = useCallback(() => {
    sendCommand('dump_buffer', -1, currentChannelArg());
  }, [currentChannelArg, sendCommand]);

  const setLogVerbosity = useCallback(
    (level: number) => {
      sendCommand('set_debug', level, currentChannelArg());
    },
    [currentChannelArg, sendCommand],
  );

  const refreshConfig = useCallback(() => {
    sendCommand('get_full_config', 0, 0);
  }, [sendCommand]);

  // Active channel name for display
  const currentChannelName = useMemo(() => {
    if (channelList.length === 0) return '-';
    const ch = channelList[channelIndex];
    const info = channels.find((c) => c.index === ch);
    return info?.tag ?? String(ch);
  }, [channelList, channelIndex, channels]);

  // Get site alias
  const getSiteAlias = useCallback(
    (sysname: string, rfss: unknown, site: unknown): string => {
      const key = String(sysname).toUpperCase();
      const alias = siteAliases?.[key]?.[String(rfss)]?.[String(site)]?.alias;
      return alias ?? `Site ${site}`;
    },
    [siteAliases],
  );

  // TG tag cache snapshot (for TalkgroupPanel)
  const tgTagCache = tgTagCacheRef.current;

  // ── Render ────────────────────────────────────────────────────────────────
  const currentChannelId = channelList[channelIndex] ?? 0;

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />

      <NavBar
        connectionError={connectionError}
        wsConnected={wsConnected}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenConfig={() => { refreshConfig(); setConfigOpen(true); }}
        onOpenAbout={() => setAboutOpen(true)}
        debugInfo={controlStats}
      />

      <Container maxWidth={false} sx={{ pt: 1, pb: 4, px: { xs: 1, sm: 2 } }}>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' },
            gap: 1.5,
            alignItems: 'start',
          }}
        >
          {/* ── LEFT COLUMN ── */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <MainDisplay
              system={currentSystem}
              freq={currentFreq}
              tgid={currentTgid}
              tgtag={currentTag}
              srcAddr={currentSrcAddr}
              encrypted={currentEncrypted}
              emergency={currentEmergency}
              channelName={currentChannelName}
              streamUrl={currentStreamUrl}
              channelId={currentChannelId}
              wsEndpoints={wsEndpoints}
              playingChannels={playingChannels}
              onToggleAudio={toggleAudio}
              onInitAudio={initAudioCtx}
              smartColors={smartColors}
              settingsSmartColors={settings.smartColors}
            />

            <ChannelControls
              captureActive={captureActive}
              errorVal={errorVal}
              onScan={scanTalkgroup}
              onHold={holdTalkgroup}
              onLockout={lockoutTalkgroup}
              onWhitelist={whitelistTalkgroup}
              onPrevChannel={prevChannel}
              onNextChannel={nextChannel}
              onTune={adjustTune}
              onCapture={toggleCapture}
              onDumpTgids={dumpTgids}
              onDumpBuffer={dumpBuffer}
              onSetLogVerbosity={setLogVerbosity}
              onTogglePlot={togglePlot}
              currentTgid={currentTgid}
            />

            <TalkgroupPanel
              presets={presets}
              tgTagCache={tgTagCache}
              currentTgid={currentTgid}
              callHistory={callHistory}
              smartColors={smartColors}
              settingsSmartColors={settings.smartColors}
              onHold={holdTalkgroup}
              onLockout={lockoutTalkgroup}
            />

            {settings.showChannelsTable && (
              <ChannelTable
                channels={channels}
                currentChannelId={currentChannelId}
                smartColors={smartColors}
                settingsSmartColors={settings.smartColors}
                onHold={holdTalkgroup}
              />
            )}

            <FrequencyTable
              nacData={nacData}
              smartColors={smartColors}
              settingsSmartColors={settings.smartColors}
              showBandPlan={settings.showBandPlan}
              showAdjacentSites={settings.showAdjacentSites}
              radioIdInFreqTable={settings.radioIdInFreqTable}
              getSiteAlias={getSiteAlias}
              onHold={holdTalkgroup}
            />
          </Box>

          {/* ── RIGHT COLUMN ── */}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <PlotPanel plots={plots} onTogglePlot={togglePlot} />

            {settings.showCallHistory && (
              <CallHistory
                entries={callHistory}
                source={settings.callHistorySource}
                smartColors={smartColors}
                settingsSmartColors={settings.smartColors}
                onClear={() => setCallHistory([])}
                maxRows={settings.callHistoryMaxRows}
              />
            )}

            {settings.trackSubscribers && (
              <SubscriberTable
                data={subscriberData}
                mode={settings.subscriberMode}
                currentSystem={currentSystem}
                smartColors={smartColors}
                settingsSmartColors={settings.smartColors}
              />
            )}
          </Box>
        </Box>
      </Container>

      <SettingsDialog
        open={settingsOpen}
        settings={settings}
        onClose={() => setSettingsOpen(false)}
        onSave={saveAllSettings}
        captureActive={captureActive}
        onCapture={toggleCapture}
        onDumpTgids={dumpTgids}
        onDumpBuffer={dumpBuffer}
        onSetLogVerbosity={setLogVerbosity}
        streamUrl={currentStreamUrl}
        wsConnected={wsConnected}
        debugInfo={controlStats}
      />

      <ConfigDialog
        open={configOpen}
        config={fullConfig}
        onClose={() => setConfigOpen(false)}
      />

      <AboutDialog
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
      />
    </ThemeProvider>
  );
}
