import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Card } from '@/components/ui/card';

export function CategoryBreakdownChart({ categories }: any) {
  const data = Object.entries(categories || {})
    .map(([key, value]: any) => ({
      category: key.replace('Cat', 'Category '),
      tCO2e: value.total_tCO2e || 0,
    }));

  return (
    <Card className="p-6">
      <h2 className="mb-4 text-xl font-semibold">Emissions by Category</h2>
      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="category" angle={-45} textAnchor="end" height={80} />
          <YAxis />
          <Tooltip formatter={(v: any) => `${v.toLocaleString()} tCO₂e`} />
          <Bar dataKey="tCO2e" fill="#10b981" radius={[8, 8, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}
