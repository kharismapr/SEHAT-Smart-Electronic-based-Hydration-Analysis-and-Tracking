import React from 'react';
import { SlidersHorizontal, Info } from 'lucide-react';

/**
 * SimulationControls Component
 * Provides manual sliders to simulate the hardware sensor inputs before initiating a measurement.
 */
export const SimulationControls = ({
  rawFeatures,
  onUpdateFeature,
  disabled = false
}) => {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-sm font-extrabold text-slate-900 uppercase tracking-wider flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-emerald-600" />
            Sensor Signal Simulation Bench
          </h3>
          <p className="text-xs text-slate-500 font-medium">
            Calibrate or simulate hardware sensor feeds before triggering a measurement session
          </p>
        </div>

        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
          <Info className="w-3 h-3 text-cyan-600" />
          Offline Testing Bench
        </span>
      </div>

      {/* Manual Sensor Input Sliders */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
        {/* PPG (BPM) slider */}
        <div className="space-y-1.5 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
          <div className="flex justify-between text-slate-700 font-semibold">
            <span>Signal: Heartbeat (PPG)</span>
            <span className="font-mono font-bold text-rose-600">{rawFeatures.bpm} BPM</span>
          </div>
          <input
            type="range"
            min="45"
            max="150"
            disabled={disabled}
            value={rawFeatures.bpm}
            onChange={(e) => onUpdateFeature('bpm', parseInt(e.target.value, 10))}
            className="w-full accent-rose-600 cursor-pointer disabled:opacity-50"
          />
          <p className="text-[10px] text-slate-400">Resting pulse sensor input</p>
        </div>

        {/* SpO2 slider */}
        <div className="space-y-1.5 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
          <div className="flex justify-between text-slate-700 font-semibold">
            <span>Signal: Oxygen Saturation (SpO₂)</span>
            <span className="font-mono font-bold text-sky-600">{rawFeatures.spo2 || 98}%</span>
          </div>
          <input
            type="range"
            min="80"
            max="100"
            disabled={disabled}
            value={rawFeatures.spo2 || 98}
            onChange={(e) => {
              onUpdateFeature('spo2', parseInt(e.target.value, 10));
              onUpdateFeature('spo2Valid', true);
            }}
            className="w-full accent-sky-600 cursor-pointer disabled:opacity-50"
          />
          <p className="text-[10px] text-slate-400">Blood oxygen saturation level</p>
        </div>

        {/* GSR slider */}
        <div className="space-y-1.5 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
          <div className="flex justify-between text-slate-700 font-semibold">
            <span>Signal: GSR Conductance</span>
            <span className="font-mono font-bold text-cyan-600">{rawFeatures.gsr} μS</span>
          </div>
          <input
            type="range"
            min="1.0"
            max="20.0"
            step="0.2"
            disabled={disabled}
            value={rawFeatures.gsr}
            onChange={(e) => onUpdateFeature('gsr', parseFloat(e.target.value))}
            className="w-full accent-cyan-600 cursor-pointer disabled:opacity-50"
          />
          <p className="text-[10px] text-slate-400">Skin electrodermal conductance</p>
        </div>
      </div>
    </div>
  );
};
