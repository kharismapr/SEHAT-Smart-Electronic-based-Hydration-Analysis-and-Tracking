import React from 'react';
import { Play, Loader2, Cpu } from 'lucide-react';

/**
 * MeasurementTrigger Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const MeasurementTrigger = ({
  isMeasuring,
  isInferring,
  measurementProgress,
  secondsRemaining,
  onStart
}) => {
  return (
    <div className="bg-white border border-[#83c4e2]/50 rounded-2xl p-6 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-4">
      <div>
        <h3 className="text-base font-extrabold text-[#054867]">
          SEHAT Sensor Measurement
        </h3>
        <p className="text-xs text-[#054867]/60 font-medium">
          Click the Button to start Measuring
        </p>
      </div>

      <div className="w-full sm:w-auto">
        {isMeasuring ? (
          <div className="min-w-[240px] space-y-1.5 bg-[#f0f7fb] border border-[#83c4e2] p-3.5 rounded-xl">
            <div className="flex items-center justify-between text-xs font-bold text-[#054867]">
              <span className="flex items-center gap-1.5 text-[#1081b7]">
                {isInferring ? (
                  <>
                    <Cpu className="w-3.5 h-3.5 animate-pulse text-[#054867]" />
                    Running ML Model...
                  </>
                ) : (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-[#1081b7]" />
                    Sampling Sensors ({secondsRemaining}s)...
                  </>
                )}
              </span>
              <span className="font-mono">
                {isInferring ? '100%' : `${measurementProgress}%`}
              </span>
            </div>
            <div className="w-full h-2 bg-[#83c4e2]/30 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-100 ease-out ${
                  isInferring ? 'bg-[#054867] w-full animate-pulse' : 'bg-[#1081b7]'
                }`}
                style={{ width: isInferring ? '100%' : `${measurementProgress}%` }}
              />
            </div>
          </div>
        ) : (
          <button
            onClick={onStart}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-bold text-sm bg-[#1081b7] hover:bg-[#054867] active:scale-95 text-white shadow-xs transition-all cursor-pointer"
          >
            <Play className="w-4 h-4 fill-white" />
            Start Measurement
          </button>
        )}
      </div>
    </div>
  );
};
