'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

// Dummy strategies data
const dummyStrategies = [
  {
    id: 1,
    name: 'Mean Reversion Strategy',
    description: 'Trades on price deviations from moving averages. Buys when price is below SMA and RSI is oversold.',
    strategy_type: 'mean_reversion',
    config: { quantity: 50, sma_period: 20, rsi_oversold: 30, rsi_overbought: 70 },
    is_active: true,
    created_at: '2024-01-10T10:00:00Z',
    updated_at: '2024-01-15T09:30:00Z'
  },
  {
    id: 2,
    name: 'Momentum Strategy',
    description: 'Follows trends using MACD and moving average crossovers. Enters on bullish momentum signals.',
    strategy_type: 'momentum',
    config: { quantity: 50, sma_fast: 20, sma_slow: 50, macd_fast: 12, macd_slow: 26 },
    is_active: false,
    created_at: '2024-01-08T14:00:00Z',
    updated_at: '2024-01-12T11:00:00Z'
  },
  {
    id: 3,
    name: 'Bollinger Bands Strategy',
    description: 'Trades on Bollinger Band breakouts and mean reversion. Enters when price touches bands.',
    strategy_type: 'bollinger_bands',
    config: { quantity: 50, period: 20, std_dev: 2 },
    is_active: true,
    created_at: '2024-01-05T09:00:00Z',
    updated_at: '2024-01-14T16:00:00Z'
  },
  {
    id: 4,
    name: 'RSI Divergence Strategy',
    description: 'Detects RSI divergences to identify potential reversals. High accuracy but lower frequency.',
    strategy_type: 'rsi_divergence',
    config: { quantity: 25, rsi_period: 14, divergence_lookback: 5 },
    is_active: false,
    created_at: '2024-01-03T12:00:00Z',
    updated_at: '2024-01-10T10:00:00Z'
  }
]

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<any[]>(dummyStrategies)
  const [loading] = useState(false)

  const toggleStrategy = (id: number, isActive: boolean) => {
    // Update local state for preview
    setStrategies(prev => prev.map(s => 
      s.id === id ? { ...s, is_active: !isActive } : s
    ))
  }

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Strategies</h1>
            <p className="text-muted-foreground mt-1">Manage your trading strategies</p>
          </div>
          <Button>Create Strategy</Button>
        </div>

        {loading ? (
          <p className="text-muted-foreground">Loading...</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {strategies.map((strategy) => (
              <Card key={strategy.id} className="hover:glow-white-hover transition-all">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span>{strategy.name}</span>
                    <span className={`text-xs px-2 py-1 rounded ${
                      strategy.is_active ? 'bg-green-500/20 text-green-500' : 'bg-muted text-muted-foreground'
                    }`}>
                      {strategy.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground mb-4">
                    {strategy.description || 'No description'}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => toggleStrategy(strategy.id, strategy.is_active)}
                    >
                      {strategy.is_active ? 'Deactivate' : 'Activate'}
                    </Button>
                    <Button variant="outline" size="sm">
                      Edit
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

