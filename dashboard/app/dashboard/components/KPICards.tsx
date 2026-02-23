import { Card } from '@/components/ui/card';
import { TrendingUp, AlertCircle, Database } from 'lucide-react';

export function KPICards({ summary }: any) {
  return (
    <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-3">

      <Card className="p-6 bg-gradient-to-br from-emerald-500 to-emerald-600 text-white">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-emerald-100">Total Scope 3</p>
            <p className="text-4xl font-bold">
              {summary.total_scope3_tCO2e?.toLocaleString()} tCO₂e
            </p>
          </div>
          <TrendingUp className="h-12 w-12 opacity-50" />
        </div>
      </Card>

      <Card className="p-6 border-red-200 bg-red-50">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-red-600">Category 11 (Sold Products)</p>
            <p className="text-4xl font-bold text-red-600">
              {summary.categories?.Cat11?.total_tCO2e?.toLocaleString() || 0} tCO₂e
            </p>
          </div>
          <AlertCircle className="h-12 w-12 text-red-600 opacity-50" />
        </div>
      </Card>

      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-gray-600">Records Processed</p>
            <p className="text-4xl font-bold">{summary.records}</p>
          </div>
          <Database className="h-12 w-12 text-gray-400" />
        </div>
      </Card>

    </div>
  );
}
