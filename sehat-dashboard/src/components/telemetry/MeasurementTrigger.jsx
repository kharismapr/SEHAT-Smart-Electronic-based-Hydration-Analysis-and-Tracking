import React, { useState } from 'react';
import { Play, Loader2, Cpu, Sliders, CheckCircle2, RotateCcw, FastForward, Activity } from 'lucide-react';

/**
 * MeasurementTrigger Component - 4-Button Hardware & Clinical Session Control
 * Buttons:
 *  - Calibrate -> sends 'c' to ESP32
 *  - Start     -> sends 's' to ESP32 & launches 30s measurement
 *  - Flush     -> sends 'f' to ESP32 (forces window calculation)
 *  - Reset     -> sends 'r' to ESP32 (clears buffer)
 */
export const MeasurementTrigger = ({
  isMeasuring,
  isInferring,
  measurementProgress,
  secondsRemaining,
  onStart,
  onCalibrate,
  onFlush,
  onReset
}) => {
  const [lastAction, setLastAction] = useState('');

  const handleCalibrate = async () => {
    setLastAction('Sent: Calibrate (c)');
    if (onCalibrate) await onCalibrate();
    setTimeout(() => setLastAction(''), 3000);
  };

  const handleStart = async () => {
    setLastAction('Sent: Start (s)');
    if (onStart) await onStart();
  };

  const handleFlush = async () => {
    setLastAction('Sent: Flush (f)');
    if (onFlush) await onFlush();
    setTimeout(() => setLastAction(''), 3000);
  };

  const handleReset = async () => {
    setLastAction('Sent: Reset (r)');
    if (onReset) await onReset();
    setTimeout(() => setLastAction(''), 3000);
  };

  return (
    <div className="bg-white border border-[#83c4e2]/50 rounded-2xl p-5 shadow-xs space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full ${isMeasuring ? 'bg-amber-500 animate-ping' : 'bg-emerald-500'}`} />
            <h3 className="text-base font-extrabold text-[#054867]">
              SEHAT Hardware & Session Controls
            </h3>
          </div>
          <p className="text-xs text-[#054867]/70 font-medium">
            Send commands directly to the ESP32 and manage your 30-second patient measurement session.
          </p>
        </div>

        {lastAction && (
          <div className="px-3 py-1 rounded-full bg-[#1081b7]/10 border border-[#1081b7]/20 text-[#1081b7] text-xs font-bold animate-in fade-in">
            {lastAction}
          </div>
        )}
      </div>

      {/* 30-Second Measurement Progress Bar (shown when active) */}
      {isMeasuring && (
        <div className="space-y-1.5 bg-[#f0f7fb] border border-[#1081b7]/40 p-4 rounded-xl shadow-xs animate-in fade-in">
          <div className="flex items-center justify-between text-xs font-bold text-[#054867]">
            <span className="flex items-center gap-1.5 text-[#1081b7]">
              {isInferring ? (
                <>
                  <Cpu className="w-4 h-4 animate-pulse text-[#054867]" />
                  Finalizing & Running ExtraTrees ML Model...
                </>
              ) : (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-[#1081b7]" />
                  Acquiring Multisensor Stream ({secondsRemaining}s remaining)...
                </>
              )}
            </span>
            <span className="font-mono text-sm font-black text-[#1081b7]">
              {isInferring ? '100%' : `${measurementProgress}%`}
            </span>
          </div>
          <div className="w-full h-2.5 bg-[#83c4e2]/30 rounded-full overflow-hidden p-0.5">
            <div
              className={`h-full rounded-full transition-all duration-100 ease-out ${
                isInferring ? 'bg-[#054867] w-full animate-pulse' : 'bg-gradient-to-r from-[#1081b7] to-[#83c4e2]'
              }`}
              style={{ width: isInferring ? '100%' : `${measurementProgress}%` }}
            />
          </div>
        </div>
      )}

      {/* 4 Dedicated Hardware Action Buttons */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-1">
        {/* 1. Calibrate ('c') */}
        <button
          type="button"
          onClick={handleCalibrate}
          title="Send 'c' command to calibrate Grove GSR open-circuit baseline"
          className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs bg-white hover:bg-slate-50 border border-[#83c4e2] text-[#054867] active:scale-95 transition-all cursor-pointer shadow-2xs"
        >
          <Sliders className="w-3.5 h-3.5 text-[#1081b7]" />
          <span>Calibrate (c)</span>
        </button>

        {/* 2. Start ('s') */}
        <button
          type="button"
          onClick={handleStart}
          disabled={isMeasuring}
          title="Send 's' command to start 30-second continuous acquisition"
          className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs bg-[#1081b7] hover:bg-[#054867] disabled:opacity-50 active:scale-95 text-white transition-all cursor-pointer shadow-sm"
        >
          <Play className="w-3.5 h-3.5 fill-white" />
          <span>Start (s)</span>
        </button>

        {/* 3. Flush ('f') */}
        <button
          type="button"
          onClick={handleFlush}
          title="Send 'f' command to flush partial window and compute features immediately"
          className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs bg-white hover:bg-slate-50 border border-[#83c4e2] text-[#054867] active:scale-95 transition-all cursor-pointer shadow-2xs"
        >
          <FastForward className="w-3.5 h-3.5 text-amber-500" />
          <span>Flush (f)</span>
        </button>

        {/* 4. Reset ('r') */}
        <button
          type="button"
          onClick={handleReset}
          title="Send 'r' command to reset recording buffer"
          className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-bold text-xs bg-white hover:bg-rose-50 border border-rose-200 text-rose-600 active:scale-95 transition-all cursor-pointer shadow-2xs"
        >
          <RotateCcw className="w-3.5 h-3.5 text-rose-500" />
          <span>Reset (r)</span>
        </button>
      </div>
    </div>
  );
};
