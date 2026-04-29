'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCurrency } from '@/lib/format'

interface PositionsProps {
  data: any[]
}

// Default dummy data if none provided
const defaultPositions = [
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
  }
]

export function Positions({ data }: PositionsProps) {
  const positions = data && data.length > 0 ? data : defaultPositions
  
  if (!positions || positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Open Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">No open positions</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Open Positions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {positions.map((position, index) => (
            <div
              key={index}
              className="border border-border rounded-lg p-4 hover:glow-white-hover transition-all"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="font-mono font-semibold">{position.tradingsymbol}</div>
                <div className={`text-sm font-bold ${position.pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  ₹{formatCurrency(position.pnl)}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm text-muted-foreground">
                <div>Qty: {position.quantity}</div>
                <div>Avg: ₹{position.average_price?.toFixed(2)}</div>
                <div>LTP: ₹{position.last_price?.toFixed(2)}</div>
                <div>Product: {position.product}</div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

