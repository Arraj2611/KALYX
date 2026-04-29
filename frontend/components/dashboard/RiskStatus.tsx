'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCurrency } from '@/lib/format'

interface RiskStatusProps {
  data: any
}

// Default dummy data
const defaultRiskStatus = {
  capital_usage_pct: 45.2,
  daily_pnl: 12500.50,
  daily_trades: 12,
  max_capital_usage_pct: 80.0,
  max_loss_per_day: 50000.0,
  max_trades_per_day: 50,
  is_breach: false,
  circuit_breaker_active: false,
  available_margin: 1250000.00,
  used_margin: 565000.00
}

export function RiskStatus({ data }: RiskStatusProps) {
  const riskData = data || defaultRiskStatus
  if (!riskData) return null

  const isBreach = riskData.is_breach || riskData.circuit_breaker_active

  return (
    <Card className={isBreach ? 'border-destructive glow-white' : ''}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Risk Status</span>
          {isBreach && (
            <span className="text-destructive text-sm font-normal animate-pulse">
              BREACH DETECTED
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-sm text-muted-foreground">Capital Usage</div>
            <div className="text-2xl font-bold mt-1">
              {riskData.capital_usage_pct?.toFixed(1)}%
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Max: {riskData.max_capital_usage_pct}%
            </div>
          </div>

          <div>
            <div className="text-sm text-muted-foreground">Daily P&L</div>
            <div className={`text-2xl font-bold mt-1 ${riskData.daily_pnl < 0 ? 'text-destructive' : ''}`}>
              ₹{formatCurrency(riskData.daily_pnl)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Max Loss: ₹{formatCurrency(riskData.max_loss_per_day)}
            </div>
          </div>

          <div>
            <div className="text-sm text-muted-foreground">Daily Trades</div>
            <div className="text-2xl font-bold mt-1">
              {riskData.daily_trades || 0}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Max: {riskData.max_trades_per_day}
            </div>
          </div>

          <div>
            <div className="text-sm text-muted-foreground">Available Margin</div>
            <div className="text-2xl font-bold mt-1">
              ₹{formatCurrency(riskData.available_margin)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Used: ₹{formatCurrency(riskData.used_margin)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

