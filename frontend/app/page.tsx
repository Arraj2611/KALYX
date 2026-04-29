'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import Link from 'next/link'

// Dummy status data
const dummyStatus = {
  status: 'healthy',
  version: '1.0.0',
  service: 'KALYX Trading System'
}

export default function Home() {
  const [status] = useState<any>(dummyStatus)
  const [loading] = useState(false)

  return (
    <main className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-5xl font-bold mb-2 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
            KALYX
          </h1>
          <p className="text-muted-foreground text-lg">Automated Index Options Trading System</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
          <Card className="hover:glow-white-hover transition-all">
            <CardHeader>
              <CardTitle>System Status</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <p className="text-muted-foreground">Loading...</p>
              ) : (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                    <p className="text-sm font-semibold">{status?.status?.toUpperCase()}</p>
                  </div>
                  <p className="text-sm text-muted-foreground">Version: {status?.version}</p>
                  <p className="text-sm text-muted-foreground mt-1">Service: {status?.service}</p>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="hover:glow-white-hover transition-all">
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Link href="/dashboard">
                <Button variant="outline" className="w-full justify-start">
                  View Dashboard
                </Button>
              </Link>
              <Link href="/strategies">
                <Button variant="outline" className="w-full justify-start">
                  Manage Strategies
                </Button>
              </Link>
              <Link href="/auth">
                <Button variant="outline" className="w-full justify-start">
                  Authentication
                </Button>
              </Link>
            </CardContent>
          </Card>

          <Card className="hover:glow-white-hover transition-all">
            <CardHeader>
              <CardTitle>System Info</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Backend:</span>
                  <span className="font-mono">Running</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Database:</span>
                  <span className="font-mono">Connected</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Redis:</span>
                  <span className="font-mono">Connected</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="mt-8">
          <h2 className="text-2xl font-bold mb-4">Features</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Live Trading</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Automated order execution with Zerodha Kite Connect API
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Strategy Engine</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Plugin-based strategy system with import/export capabilities
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Backtesting</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Historical data backtesting with comprehensive metrics
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Risk Management</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Capital usage limits, daily loss limits, and circuit breakers
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </main>
  )
}

