'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { RiskStatus } from '@/components/dashboard/RiskStatus'
import { Positions } from '@/components/dashboard/Positions'
import { Orders } from '@/components/dashboard/Orders'
import { formatCurrency } from '@/lib/format'

// Dummy data for preview
const dummyRiskStatus = {
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

const dummyPositions = [
  {
    tradingsymbol: 'NIFTY24JAN24500CE',
    exchange: 'NFO',
    quantity: 50,
    average_price: 245.50,
    last_price: 258.75,
    pnl: 662.50,
    product: 'MIS'
  },
  {
    tradingsymbol: 'BANKNIFTY24JAN48500PE',
    exchange: 'NFO',
    quantity: 25,
    average_price: 180.25,
    last_price: 195.50,
    pnl: 381.25,
    product: 'MIS'
  },
  {
    tradingsymbol: 'NIFTY24JAN24400CE',
    exchange: 'NFO',
    quantity: 50,
    average_price: 320.00,
    last_price: 305.25,
    pnl: -737.50,
    product: 'MIS'
  }
]

const dummyOrders = [
  {
    id: 1,
    order_id: '24011500123456',
    tradingsymbol: 'NIFTY24JAN24500CE',
    status: 'COMPLETE',
    quantity: 50,
    filled_quantity: 50,
    average_price: 245.50,
    price: 245.50,
    transaction_type: 'BUY',
    created_at: '2024-01-15T10:30:00Z'
  },
  {
    id: 2,
    order_id: '24011500123457',
    tradingsymbol: 'BANKNIFTY24JAN48500PE',
    status: 'COMPLETE',
    quantity: 25,
    filled_quantity: 25,
    average_price: 180.25,
    price: 180.25,
    transaction_type: 'BUY',
    created_at: '2024-01-15T10:35:00Z'
  },
  {
    id: 3,
    order_id: '24011500123458',
    tradingsymbol: 'NIFTY24JAN24400CE',
    status: 'COMPLETE',
    quantity: 50,
    filled_quantity: 50,
    average_price: 320.00,
    price: 320.00,
    transaction_type: 'BUY',
    created_at: '2024-01-15T11:00:00Z'
  },
  {
    id: 4,
    order_id: '24011500123459',
    tradingsymbol: 'NIFTY24JAN24600CE',
    status: 'PENDING',
    quantity: 50,
    filled_quantity: 0,
    average_price: null,
    price: 185.75,
    transaction_type: 'SELL',
    created_at: '2024-01-15T11:15:00Z'
  },
  {
    id: 5,
    order_id: '24011500123460',
    tradingsymbol: 'BANKNIFTY24JAN49000CE',
    status: 'COMPLETE',
    quantity: 25,
    filled_quantity: 25,
    average_price: 145.50,
    price: 145.50,
    transaction_type: 'SELL',
    created_at: '2024-01-15T11:20:00Z'
  }
]

export default function DashboardPage() {
  const [riskStatus] = useState<any>(dummyRiskStatus)
  const [positions] = useState<any[]>(dummyPositions)
  const [orders] = useState<any[]>(dummyOrders)

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Dashboard</h1>
            <p className="text-muted-foreground mt-1">Real-time trading overview</p>
          </div>
        </div>

        {/* Risk Status */}
        <RiskStatus data={riskStatus} />

        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Equity Curve */}
          <div className="lg:col-span-2">
            <EquityCurve />
          </div>

          {/* Quick Stats */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Daily P&L</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">
                  ₹{formatCurrency(riskStatus?.daily_pnl)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Capital Usage</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">
                  {riskStatus?.capital_usage_pct?.toFixed(1) || '0.0'}%
                </div>
                <div className="text-sm text-muted-foreground mt-2">
                  Available: ₹{formatCurrency(riskStatus?.available_margin)}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Positions and Orders */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Positions data={positions} />
          <Orders data={orders} />
        </div>
      </div>
    </div>
  )
}

