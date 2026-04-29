'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface OrdersProps {
  data: any[]
}

// Default dummy data if none provided
const defaultOrders = [
  {
    id: 1,
    order_id: '24011500123456',
    tradingsymbol: 'NIFTY24JAN24500CE',
    status: 'COMPLETE',
    quantity: 50,
    filled_quantity: 50,
    average_price: 245.50,
    price: 245.50,
    transaction_type: 'BUY'
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
    transaction_type: 'BUY'
  },
  {
    id: 3,
    order_id: '24011500123458',
    tradingsymbol: 'NIFTY24JAN24400CE',
    status: 'PENDING',
    quantity: 50,
    filled_quantity: 0,
    average_price: null,
    price: 320.00,
    transaction_type: 'BUY'
  }
]

export function Orders({ data }: OrdersProps) {
  const orders = data && data.length > 0 ? data : defaultOrders
  
  if (!orders || orders.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Orders</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">No recent orders</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Orders</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {orders.slice(0, 10).map((order) => (
            <div
              key={order.id}
              className="border border-border rounded p-3 hover:glow-white-hover transition-all"
            >
              <div className="flex items-center justify-between mb-1">
                <div className="font-mono text-sm">{order.tradingsymbol}</div>
                <div className={`text-xs px-2 py-1 rounded ${
                  order.status === 'COMPLETE' ? 'bg-green-500/20 text-green-500' :
                  order.status === 'PENDING' ? 'bg-yellow-500/20 text-yellow-500' :
                  'bg-muted text-muted-foreground'
                }`}>
                  {order.status}
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                {order.transaction_type} {order.quantity} @ ₹{order.average_price?.toFixed(2) || order.price?.toFixed(2) || 'N/A'}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

