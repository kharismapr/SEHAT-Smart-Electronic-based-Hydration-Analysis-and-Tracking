import React, { useState } from 'react';
import { useSehatTelemetry } from './hooks/useSehatTelemetry';
import { Sidebar } from './components/layout/Sidebar';
import { VitalStatusBanner } from './components/telemetry/VitalStatusBanner';
import { SensorGrid } from './components/telemetry/SensorGrid';
import { MeasurementTrigger } from './components/telemetry/MeasurementTrigger';
import { TelemetryChart } from './components/charts/TelemetryChart';
import { HistoryTable } from './components/history/HistoryTable';
import { exportToCSVString } from './utils/calculations';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' | 'history'
  
  // Device hardware state (Ready to link to Web Bluetooth / Serial API later)
  const [connectionStatus, setConnectionStatus] = useState('Connected'); // 'Connected' | 'Connecting' | 'Disconnected'
  const [batteryLevel, setBatteryLevel] = useState(84); // Wearable battery percentage

  const {
    rawSensors,
    liveInference,
    latestResult,
    history,
    isMeasuring,
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

  const displayHours = latestResult
    ? latestResult.hoursSinceHydration
    : liveInference.hoursSinceHydration;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col lg:flex-row antialiased">
      {/* 1. Sidebar Navigation with Connection & Battery Status */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        historyCount={history.length}
        connectionStatus={connectionStatus}
        batteryLevel={batteryLevel}
      />

      {/* 2. Main Content Workspace */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-4 flex items-center justify-between sticky top-0 z-40">
          <div>
            <h2 className="text-base font-extrabold text-slate-900">
              {activeTab === 'dashboard' ? 'Measurement' : 'History'}
            </h2>
            <p className="text-xs text-slate-500 font-medium">
              {activeTab === 'dashboard'
                ? 'SEHAT Hydration Analysis'
                : 'Measurement records'}
            </p>
          </div>
        </header>

        <main className="p-6 lg:p-8 space-y-6 max-w-5xl">
          {activeTab === 'dashboard' ? (
            <>
              {/* Start Measurement Trigger */}
              <MeasurementTrigger
                isMeasuring={isMeasuring}
                measurementProgress={measurementProgress}
                secondsRemaining={secondsRemaining}
                onStart={startMeasurement}
              />

              {/* Classification & Hours Since Hydration Banner */}
              <section className="space-y-2">
                <VitalStatusBanner
                  hoursSinceHydration={displayHours}
                />
              </section>

              {/* Raw Sensor Feeds */}
              <section className="space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Raw Sensor Data
                </h3>
                <SensorGrid reading={latestResult ? latestResult : rawSensors} />
              </section>
            </>
          ) : (
            <>
              {/* History Chart */}
              <section>
                <TelemetryChart history={history} />
              </section>

              {/* History Table */}
              <section>
                <HistoryTable
                  history={history}
                  onClear={clearHistory}
                  onExport={handleExportCSV}
                />
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
