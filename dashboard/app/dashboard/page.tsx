'use client';

import { useState } from 'react';
import { UploadZone } from './components/UploadZone';
import { KPICards } from './components/KPICards';
import { CategoryBreakdownChart } from './components/CategoryBreakdownChart';
import { DataTables } from './components/DataTables';
import { calculateScope3 } from "../../lib/api";

import { Loader2 } from 'lucide-react';

export default function Dashboard() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFilesUploaded = async (files: File[]) => {
    setLoading(true);
    setError(null);

    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });

    try {
      const json = await calculateScope3(formData);
      setData(json);
    } catch (err: any) {
      console.error("ERROR:", err);
      setError(err.message || "Error communicating with backend");
    }

    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-gray-900">ScopeChain AI</h1>
          <p className="text-lg text-gray-600">Enterprise Scope 3 Emissions Dashboard</p>
        </div>

        <UploadZone onFilesUploaded={handleFilesUploaded} />

        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-16 w-16 animate-spin text-emerald-600" />
            <span className="ml-4 text-lg text-gray-500">Processing your data...</span>
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
            <p className="font-semibold">Calculation failed</p>
            <p className="text-sm mt-1">{error}</p>
          </div>
        )}

        {data && !loading && (
          <>
            <KPICards summary={data.summary} />
            <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-2">
              <CategoryBreakdownChart categories={data.summary.categories} />
              <div className="rounded-xl bg-white p-6 shadow-sm">
                <h2 className="mb-4 text-xl font-semibold">Trend Over Time</h2>
                <p className="text-gray-500">Connect your data to see trends</p>
              </div>
            </div>
            <DataTables normalizedData={data.normalized_data} />
          </>
        )}
      </div>
    </div>
  );
}
