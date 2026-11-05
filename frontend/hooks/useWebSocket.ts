import { useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: any) => void
  onError?: (error: Event) => void
  onOpen?: () => void
  onClose?: () => void
}

export function useWebSocket(url: string, options: UseWebSocketOptions = {}) {
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const apiKey = process.env.NEXT_PUBLIC_CONTROL_API_KEY || ''
    const wsUrl = apiUrl.replace('http', 'ws') + '/ws' + (apiKey ? `?token=${encodeURIComponent(apiKey)}` : '')
    
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      options.onOpen?.()
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        options.onMessage?.(data)
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }

    ws.onerror = (error) => {
      options.onError?.(error)
    }

    ws.onclose = () => {
      setIsConnected(false)
      options.onClose?.()
    }

    wsRef.current = ws

    return () => {
      ws.close()
    }
  }, [url])

  const sendMessage = (data: any) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify(data))
    }
  }

  return { isConnected, sendMessage }
}

