import React, { useState, useEffect, useRef } from 'react';
import {
  Terminal,
  X,
  Play,
  Square,
  RefreshCw,
  Trash2,
  Send,
  Radio,
  ArrowDownCircle
} from 'lucide-react';
import { HistoryService } from '../../services/historyService';
import { formatTimeOnly } from '../../utils/calculations';

/**
 * SerialMonitorDrawer Component
 * Slide-over sidebar displaying the live CLI output from serial_bridge.py,
 * COM port selection, Start/Stop process controls, and direct serial command input.
 */
export const SerialMonitorDrawer = ({
  isOpen,
  onClose,
  isConnected,
  bridgeRunning,
  selectedPort,
  onSelectPort,
  onStartBridge,
  onStopBridge
}) => {
  const [logs, setLogs] = useState([]);
  const [ports, setPorts] = useState([]);
  const [pid, setPid] = useState(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [commandInput, setCommandInput] = useState('');
  const [isRefreshingPorts, setIsRefreshingPorts] = useState(false);
  const logContainerRef = useRef(null);

  // Load available COM ports when drawer opens
  const loadPorts = async () => {
    setIsRefreshingPorts(true);
    const detected = await HistoryService.fetchBridgePorts();
    setPorts(detected);
    setIsRefreshingPorts(false);
  };

  useEffect(() => {
    if (isOpen) {
      loadPorts();
    }
  }, [isOpen]);

  // Poll bridge status and CLI logs while drawer is open
  useEffect(() => {
    if (!isOpen) return;
    let isMounted = true;

    const pollLogs = async () => {
      const status = await HistoryService.fetchBridgeStatus();
      if (isMounted && status) {
        setLogs(Array.isArray(status.logs) ? status.logs : []);
        setPid(status.pid || null);
      }
    };

    pollLogs();
    const interval = setInterval(pollLogs, 400);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isOpen, bridgeRunning]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleClearLogs = async () => {
    await HistoryService.clearBridgeLogs();
    setLogs([]);
  };

  const handleSendCommand = async (e) => {
    e.preventDefault();
    const trimmed = commandInput.trim();
    if (!trimmed) return;
    await HistoryService.sendDeviceCommand(trimmed);
    setCommandInput('');
  };

  const getLineColor = (line) => {
    const text = line.text || '';
    if (line.level === 'error' || line.level === 'stderr' || text.includes('[Error]') || text.includes('[Serial Disconnected]')) {
      return 'text-rose-400 font-semibold';
    }
    if (text.includes('[Connected]') || text.includes('⭐')) {
      return 'text-emerald-400 font-semibold';
    }
    if (text.includes('[Dashboard]') || text.includes('[Connecting]') || text.includes('[Retrying]') || text.includes('[Dashboard Command')) {
      return 'text-amber-300';
    }
    if (text.includes('[ESP32]')) {
      return 'text-sky-200';
    }
    return 'text-slate-300';
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Subtle backdrop */}
      <div
        className="fixed inset-0 bg-[#054867]/30 backdrop-blur-[2px] transition-opacity"
        onClick={onClose}
      />

      {/* Slide-over Sidebar Panel */}
      <aside className="relative z-10 w-full max-w-lg bg-[#032536] text-white h-full shadow-2xl border-l border-[#83c4e2]/30 flex flex-col">
        {/* 1. Drawer Header */}
        <div className="px-5 py-4 bg-[#054867] border-b border-[#83c4e2]/25 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-white/10 border border-white/15 text-[#83c4e2]">
              <Terminal className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-extrabold tracking-wide text-white">
                  Serial Bridge & Monitor
                </h2>
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                    isConnected
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/30'
                      : bridgeRunning
                        ? 'bg-amber-500/20 text-amber-300 border border-amber-400/30'
                        : 'bg-rose-500/20 text-rose-300 border border-rose-400/30'
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      isConnected
                        ? 'bg-emerald-400'
                        : bridgeRunning
                          ? 'bg-amber-400 animate-pulse'
                          : 'bg-rose-400'
                    }`}
                  />
                  {isConnected
                    ? 'ESP32 Linked'
                    : bridgeRunning
                      ? 'Bridge Active'
                      : 'Stopped'}
                </span>
              </div>
              <p className="text-[11px] text-[#83c4e2]/80 font-mono">
                {bridgeRunning
                  ? `serial_bridge.py running${pid ? ` (PID ${pid})` : ''}`
                  : 'Process idle • Ready to launch'}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            title="Close Serial Monitor"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 2. Bridge Process & COM Port Controls */}
        <div className="px-5 py-3.5 bg-[#043249] border-b border-[#83c4e2]/20 space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            {/* COM Port Selector */}
            <div className="flex items-center gap-1.5 flex-1 min-w-[170px]">
              <select
                value={selectedPort}
                onChange={(e) => onSelectPort(e.target.value)}
                disabled={bridgeRunning}
                className="flex-1 bg-[#021e2c] border border-[#83c4e2]/30 rounded-xl px-3 py-1.5 text-xs text-white font-mono outline-none focus:border-[#83c4e2] disabled:opacity-50"
              >
                <option value="">Auto-detect COM Port</option>
                {ports.map((p) => (
                  <option key={p.port} value={p.port}>
                    {p.port} — {p.description}
                  </option>
                ))}
              </select>

              <button
                type="button"
                onClick={loadPorts}
                disabled={bridgeRunning || isRefreshingPorts}
                title="Refresh available COM ports"
                className="p-2 rounded-xl bg-[#021e2c] hover:bg-white/10 border border-[#83c4e2]/30 text-[#83c4e2] disabled:opacity-40 cursor-pointer transition-colors"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRefreshingPorts ? 'animate-spin' : ''}`} />
              </button>
            </div>

            {/* Start / Stop Bridge Button */}
            {bridgeRunning ? (
              <button
                type="button"
                onClick={onStopBridge}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white shadow-xs transition-colors cursor-pointer"
              >
                <Square className="w-3.5 h-3.5 fill-white" />
                Stop Bridge
              </button>
            ) : (
              <button
                type="button"
                onClick={onStartBridge}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs transition-colors cursor-pointer"
              >
                <Play className="w-3.5 h-3.5 fill-white" />
                Run Bridge
              </button>
            )}
          </div>

          {/* Toolbar: Log count, Auto-scroll, Clear */}
          <div className="flex items-center justify-between text-[11px] text-[#83c4e2]/80 pt-1">
            <span className="font-mono">{logs.length} CLI lines captured</span>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setAutoScroll(!autoScroll)}
                className={`inline-flex items-center gap-1 cursor-pointer transition-colors ${
                  autoScroll ? 'text-emerald-300 font-semibold' : 'text-white/50 hover:text-white/80'
                }`}
              >
                <ArrowDownCircle className="w-3.5 h-3.5" />
                Auto-scroll
              </button>
              <button
                type="button"
                onClick={handleClearLogs}
                className="inline-flex items-center gap-1 text-white/60 hover:text-rose-300 cursor-pointer transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear
              </button>
            </div>
          </div>
        </div>

        {/* 3. Terminal CLI Output Stream */}
        <div
          ref={logContainerRef}
          className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1 bg-[#021824] selection:bg-[#1081b7] selection:text-white"
        >
          {logs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-[#83c4e2]/40 space-y-2 px-6">
              <Radio className="w-7 h-7 stroke-[1.5]" />
              <p className="text-xs font-sans font-medium text-[#83c4e2]/60">
                No serial output yet.
              </p>
              <p className="text-[11px] font-sans">
                Click <strong>Run Bridge</strong> above to launch <code className="text-[#83c4e2]">serial_bridge.py</code> and stream live ESP32 serial output here.
              </p>
            </div>
          ) : (
            logs.map((item) => (
              <div key={item.id} className="leading-relaxed break-words flex gap-2 hover:bg-white/5 px-1.5 py-0.5 rounded">
                <span className="text-[#83c4e2]/40 shrink-0 select-none text-[10px] pt-0.5">
                  {formatTimeOnly(item.timestamp)}
                </span>
                <span className={getLineColor(item)}>{item.text}</span>
              </div>
            ))
          )}
        </div>

        {/* 4. Direct Serial Command Input */}
        <form
          onSubmit={handleSendCommand}
          className="p-3.5 bg-[#043249] border-t border-[#83c4e2]/25 space-y-2"
        >
          <div className="flex items-center gap-1.5 text-[10px] text-[#83c4e2]/80">
            <span className="uppercase font-bold tracking-wider">Quick Send:</span>
            {[
              { cmd: 'c', label: 'c (Calibrate)' },
              { cmd: 's', label: 's (Start)' },
              { cmd: 'f', label: 'f (Flush)' },
              { cmd: 'r', label: 'r (Reset)' }
            ].map((q) => (
              <button
                key={q.cmd}
                type="button"
                onClick={() => HistoryService.sendDeviceCommand(q.cmd)}
                className="px-2 py-0.5 rounded bg-[#021e2c] hover:bg-[#1081b7] text-white font-mono border border-[#83c4e2]/30 transition-colors cursor-pointer"
              >
                {q.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={commandInput}
              onChange={(e) => setCommandInput(e.target.value)}
              placeholder="Send serial command to ESP32 (e.g. c, s, f, r)..."
              className="flex-1 bg-[#021e2c] border border-[#83c4e2]/30 focus:border-[#83c4e2] rounded-xl px-3 py-2 text-xs font-mono text-white placeholder:text-white/35 outline-none"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-[#1081b7] hover:bg-[#83c4e2] hover:text-[#054867] text-white transition-colors cursor-pointer"
            >
              <Send className="w-3.5 h-3.5" />
              Send
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
};
