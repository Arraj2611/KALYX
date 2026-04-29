'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

export default function AuthPage() {
  const [requestToken, setRequestToken] = useState('')
  const [status, setStatus] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    if (!requestToken) return

    setLoading(true)
    try {
      const response = await api.post('/auth/login', {
        request_token: requestToken
      })
      setStatus(response.data)
      setRequestToken('')
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const fetchStatus = async () => {
    try {
      const response = await api.get('/auth/status')
      setStatus(response.data)
    } catch (error) {
      console.error('Failed to fetch auth status:', error)
    }
  }

  return (
    <div className="min-h-screen bg-background p-6 flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Zerodha Authentication</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">
              Request Token
            </label>
            <input
              type="text"
              value={requestToken}
              onChange={(e) => setRequestToken(e.target.value)}
              placeholder="Enter request token from Zerodha"
              className="w-full px-3 py-2 bg-background border border-input rounded-md text-foreground"
            />
            <p className="text-xs text-muted-foreground mt-2">
              Get your request token from: https://kite.trade/connect/login?api_key=YOUR_API_KEY
            </p>
          </div>

          <Button
            onClick={handleLogin}
            disabled={loading || !requestToken}
            className="w-full"
          >
            {loading ? 'Logging in...' : 'Login'}
          </Button>

          <Button
            variant="outline"
            onClick={fetchStatus}
            className="w-full"
          >
            Check Status
          </Button>

          {status && (
            <div className="mt-4 p-4 bg-muted rounded-md">
              <div className="text-sm">
                <div className="mb-2">
                  <span className="text-muted-foreground">Status: </span>
                  <span className={status.is_valid ? 'text-green-500' : 'text-red-500'}>
                    {status.is_valid ? 'Authenticated' : 'Not Authenticated'}
                  </span>
                </div>
                {status.user_id && (
                  <div>
                    <span className="text-muted-foreground">User ID: </span>
                    <span className="font-mono">{status.user_id}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

