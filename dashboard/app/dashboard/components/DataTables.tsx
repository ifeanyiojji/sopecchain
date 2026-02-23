'use client';

import { Card } from '@/components/ui/card';

interface CalculationRow {
  record_id: number;
  Cat1_tCO2e: number;
  Cat1_ci_95: string;
  Cat4_tCO2e: number;
  Cat4_ci_95: string;
  Cat11_tCO2e: number;
  Cat11_ci_95: string;
  Total_Scope3_tCO2e: number;
}

export function DataTables({ normalizedData }: { normalizedData: CalculationRow[] }) {
  if (!normalizedData || normalizedData.length === 0) {
    return (
      <Card className="mt-8 p-6">
        <h2 className="mb-4 text-xl font-semibold">Recent Records</h2>
        <div className="text-center py-12 text-gray-500">
          Upload data to see normalized and calculated results
        </div>
      </Card>
    );
  }

  return (
    <Card className="mt-8 p-6 overflow-x-auto">
      <h2 className="mb-4 text-xl font-semibold">
        Calculation Results ({normalizedData.length} records)
      </h2>
      <table className="w-full text-sm text-left">
        <thead className="text-xs text-gray-500 uppercase bg-gray-50">
          <tr>
            <th className="px-4 py-3">#</th>
            <th className="px-4 py-3">Cat 1 (Diesel)</th>
            <th className="px-4 py-3">Cat 4 (Water Hauling)</th>
            <th className="px-4 py-3">Cat 11 (Sold Products)</th>
            <th className="px-4 py-3 font-bold">Total Scope 3</th>
          </tr>
        </thead>
        <tbody>
          {normalizedData.map((row) => (
            <tr key={row.record_id} className="border-b hover:bg-gray-50">
              <td className="px-4 py-3 text-gray-500">{row.record_id + 1}</td>
              <td className="px-4 py-3">
                {row.Cat1_tCO2e.toFixed(4)}
                <span className="ml-1 text-xs text-gray-400">{row.Cat1_ci_95}</span>
              </td>
              <td className="px-4 py-3">
                {row.Cat4_tCO2e.toFixed(4)}
                <span className="ml-1 text-xs text-gray-400">{row.Cat4_ci_95}</span>
              </td>
              <td className="px-4 py-3">
                {row.Cat11_tCO2e.toFixed(4)}
                <span className="ml-1 text-xs text-gray-400">{row.Cat11_ci_95}</span>
              </td>
              <td className="px-4 py-3 font-semibold text-emerald-700">
                {row.Total_Scope3_tCO2e.toFixed(4)} tCO2e
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="bg-emerald-50 font-semibold">
          <tr>
            <td className="px-4 py-3">Total</td>
            <td className="px-4 py-3">
              {normalizedData.reduce((s, r) => s + r.Cat1_tCO2e, 0).toFixed(4)}
            </td>
            <td className="px-4 py-3">
              {normalizedData.reduce((s, r) => s + r.Cat4_tCO2e, 0).toFixed(4)}
            </td>
            <td className="px-4 py-3">
              {normalizedData.reduce((s, r) => s + r.Cat11_tCO2e, 0).toFixed(4)}
            </td>
            <td className="px-4 py-3 text-emerald-700">
              {normalizedData.reduce((s, r) => s + r.Total_Scope3_tCO2e, 0).toFixed(4)} tCO2e
            </td>
          </tr>
        </tfoot>
      </table>
    </Card>
  );
}
