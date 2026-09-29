import React, { useState } from 'react';
import { Download, Trash2, Filter, ChevronLeft, ChevronRight, FileSpreadsheet } from 'lucide-react';
import { formatDateTime } from '../../utils/calculations';

/**
 * HistoryTable Component (Light Mode)
 * Displays persistent measurement logs with filtering and CSV export.
 */
export const HistoryTable = ({ history = [], onClear, onExport }) => {
  const [filter, setFilter] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 8;

  const filteredHistory = history.filter(item => {
    if (filter === 'ALL') return true;
    const isAtRisk = item.hoursSinceHydration > 10;
    return filter === 'AT_RISK' ? isAtRisk : !isAtRisk;
  });

  const totalPages = Math.ceil(filteredHistory.length / itemsPerPage) || 1;
  const paginatedData = filteredHistory.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-5">
      {/* Header with actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <h3 className="text-base font-extrabold text-slate-900 tracking-tight flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
            Measurement History Log
          </h3>
          <p className="text-xs text-slate-500 font-medium">
            Chronological records stored locally ({filteredHistory.length} entries)
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Status Filter */}
          <div className="flex items-center bg-slate-50 p-1 rounded-xl border border-slate-200 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-500 ml-2 mr-1" />
            <select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setCurrentPage(1);
              }}
              aria-label="Filter records by hydration status"
              className="bg-transparent text-slate-700 font-medium py-1 pr-2 outline-none cursor-pointer text-xs"
            >
              <option value="ALL">All Records</option>
              <option value="WELL_HYDRATED">Well Hydrated</option>
              <option value="AT_RISK">At Risk</option>
            </select>
          </div>

          {/* Export to CSV */}
          <button
            onClick={onExport}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 transition-colors cursor-pointer"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>

          {/* Clear History */}
          <button
            onClick={onClear}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 transition-colors cursor-pointer"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear
          </button>
        </div>
      </div>

      {/* Table Data */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-slate-700">
          <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[11px] font-bold border-b border-slate-200">
            <tr>
              <th className="py-3 px-4">Timestamp</th>
              <th className="py-3 px-4">PPG (BPM)</th>
              <th className="py-3 px-4">GSR (μS)</th>
              <th className="py-3 px-4">Temp (°C)</th>
              <th className="py-3 px-4">Humidity</th>
              <th className="py-3 px-4">Hours Dry</th>
              <th className="py-3 px-4">Classification</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 font-mono">
            {paginatedData.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-slate-400 font-sans">
                  No records match the current filter.
                </td>
              </tr>
            ) : (
              paginatedData.map((row) => {
                const isAtRisk = row.hoursSinceHydration > 10;
                return (
                  <tr key={row.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-3 px-4 text-slate-500 font-sans font-medium">
                      {formatDateTime(row.timestamp)}
                    </td>
                    <td className="py-3 px-4 text-rose-600 font-bold">{row.bpm}</td>
                    <td className="py-3 px-4 text-cyan-700 font-bold">{row.gsr}</td>
                    <td className="py-3 px-4 text-amber-700 font-medium">{row.temperature}°C</td>
                    <td className="py-3 px-4 text-emerald-700 font-medium">{row.humidity}%</td>
                    <td className="py-3 px-4 font-black text-slate-900">
                      {Number(row.hoursSinceHydration).toFixed(1)}h
                    </td>
                    <td className="py-3 px-4 font-sans">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase ${
                          isAtRisk
                            ? 'bg-rose-100 text-rose-700 border border-rose-200'
                            : 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                        }`}
                      >
                        {isAtRisk ? 'In Risk of Dehydration' : 'Well Hydrated'}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-xs text-slate-500 font-medium">
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              aria-label="Previous Page"
              className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer text-slate-700"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              aria-label="Next Page"
              className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer text-slate-700"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
