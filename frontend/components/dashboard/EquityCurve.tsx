'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export function EquityCurve() {
  const [data, setData] = useState<any[]>([])

  useEffect(() => {
    // Realistic equity curve data
    const baseEquity = 1000000
    const mockData = Array.from({ length: 30 }, (_, i) => {
      // Simulate realistic equity curve with some volatility
      const trend = i * 500 // Upward trend
      const volatility = Math.sin(i / 3) * 2000 + Math.random() * 1000 - 500
      const equity = baseEquity + trend + volatility
      return {
        date: `Day ${i + 1}`,
        equity: Math.max(900000, equity) // Floor at 900k
      }
    })
    setData(mockData)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Equity Curve</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="date" stroke="#888" />
            <YAxis stroke="#888" />
            <Tooltip
              contentStyle={{
                backgroundColor: '#000',
                border: '1px solid #333',
                borderRadius: '4px'
              }}
            />
            <Line
              type="monotone"
              dataKey="equity"
              stroke="#fff"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

