import React from 'react';
import { useSehatTelemetry } from './hooks/useSehatTelemetry';
import { VitalStatusBanner } from './components/telemetry/VitalStatusBanner';
import { SensorGrid } from './components/telemetry/SensorGrid';
import { MeasurementTrigger } from './components/telemetry/MeasurementTrigger';
import { HistoryTable } from './components/history/HistoryTable';
import { exportToCSVString } from './utils/calculations';
import { Radio, Battery, BatteryMedium, BatteryLow } from 'lucide-react';

/**
 * SEHAT Single-Page All-in-One Dashboard
 * Palette: #054867 (Deep Ocean), #1081b7 (Vibrant Azure), #83c4e2 (Soft Sky), White
 */
export default function App() {
  // Device hardware status
  const connectionStatus = 'Connected';
  const batteryLevel = 84;

  const {
    rawSensors,
    latestResult,
    history,
    isMeasuring,
    isInferring,
    measurementProgress,
    secondsRemaining,
    startMeasurement,
    clearHistory
  } = useSehatTelemetry();

  // Export local history to CSV
  const handleExportCSV = () => {
    const csvContent = exportToCSVString(history);
    if (!csvContent) return;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `SEHAT_measurements_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getBatteryIcon = (level) => {
    if (level <= 20) return <BatteryLow className="w-4 h-4 text-amber-500" />;
    if (level <= 60) return <BatteryMedium className="w-4 h-4 text-[#1081b7]" />;
    return <Battery className="w-4 h-4 text-[#1081b7]" />;
  };

  const displayHours = latestResult ? latestResult.hoursSinceHydration : null;
  const currentSensorDisplay = isMeasuring ? rawSensors : (latestResult || rawSensors);

  return (
    <div className="min-h-screen bg-[#f4f8fa] text-[#054867] flex flex-col antialiased">
      {/* 1. Sleek Top Navigation Bar */}
      <header
        className="w-full text-white shadow-md sticky top-0 z-50 px-6 lg:px-12 py-4 flex items-center justify-between border-b border-[#83c4e2]/30"
        style={{
          background: 'linear-gradient(90deg, #054867 0%, #1081b7 100%)'
        }}
      >
        <div className="flex items-center gap-3">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <h1 className="text-xl lg:text-2xl font-black tracking-tight text-white font-sans">
                SEHAT
              </h1>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-white/15 border border-white/25 text-[#83c4e2]">
                Dashboard
              </span>
            </div>
            <p className="text-[11px] text-[#83c4e2] font-medium tracking-wide">
              Smart Electronic-based Hydration Analysis & Tracking
            </p>
          </div>
        </div>

        {/* Live Hardware Telemetry Status */}
        <div className="flex items-center gap-2.5 sm:gap-3">
          {/* Connection Status Pill */}
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-white/10 border border-white/20 backdrop-blur-md text-white shadow-xs">
            <span className="w-2 h-2 rounded-full bg-[#83c4e2] shadow-[0_0_8px_#83c4e2]" />
            <span className="hidden sm:inline">{connectionStatus}</span>
            <Radio className="w-3.5 h-3.5 text-[#83c4e2]" />
          </div>

          {/* Battery Status Pill */}
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-mono font-bold bg-white/10 border border-white/20 backdrop-blur-md text-white shadow-xs">
            {getBatteryIcon(batteryLevel)}
            <span>{batteryLevel}%</span>
          </div>
        </div>
      </header>

      {/* 2. Main Single-Page Workspace */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        
        {/* Sampling Trigger Protocol */}
        <section>
          <MeasurementTrigger
            isMeasuring={isMeasuring}
            isInferring={isInferring}
            measurementProgress={measurementProgress}
            secondsRemaining={secondsRemaining}
            onStart={startMeasurement}
          />
        </section>

        {/* Prediction Target & Classification Status Banner */}
        <section className="space-y-2">
          <VitalStatusBanner
            hoursSinceHydration={displayHours}
            isMeasuring={isMeasuring}
            isInferring={isInferring}
          />
        </section>

        {/* Multisensor Data Stream Grid */}
        <section className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-[#054867]/60">
            Multisensor Live Streams
          </h3>
          <SensorGrid
            reading={currentSensorDisplay}
            isLive={isMeasuring}
          />
        </section>

        {/* Specimen History Table directly below */}
        <section className="pt-2">
          <HistoryTable
            history={history}
            onClear={clearHistory}
            onExport={handleExportCSV}
          />
        </section>

      </main>

      {/* 3. Subtle Footer */}
      <footer className="border-t border-[#83c4e2]/30 py-4 text-center text-xs text-[#054867]/60 bg-white/60">
        SEHAT System • Edge Biosignal Intelligence & Hydration Ingestion Pipeline
      </footer>
    </div>
  );
}
