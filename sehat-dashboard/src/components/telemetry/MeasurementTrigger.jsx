import React from 'react';
import { Play, Loader2 } from 'lucide-react';

/**
 * MeasurementTrigger Component (Clean & Focused)
 */
export const MeasurementTrigger = ({
  isMeasuring,
  measurementProgress,
  secondsRemaining,
  onStart
}) => {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
      <div>
        <h3 className="text-base font-extrabold text-slate-900">
          Hydration Measurement
        </h3>
        <p className="text-xs text-slate-500 font-medium">
          Sample sensor signals and compute hydration status
        </p>
      </div>

      <div className="w-full sm:w-auto">
        {isMeasuring ? (
          <div className="min-w-[220px] space-y-1.5 bg-slate-50 border border-slate-200 p-3.5 rounded-xl">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700">
              <span className="flex items-center gap-1.5 text-emerald-600">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Measuring ({secondsRemaining}s)...
              </span>
              <span className="font-mono">{measurementProgress}%</span>
            </div>
            <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-500 transition-all duration-100 ease-out"
                style={{ width: `${measurementProgress}%` }}
              />
            </div>
          </div>
        ) : (
          <button
            onClick={onStart}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-5 py-3 rounded-xl font-bold text-sm bg-emerald-600 hover:bg-emerald-700 active:scale-95 text-white shadow-sm transition-all cursor-pointer"
          >
            <Play className="w-4 h-4 fill-white" />
            Start Measurement
          </button>
        )}
      </div>
    </div>
  );
};
