import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
// The backend requires this key on every request. NEXT_PUBLIC_ values are visible in the browser bundle,
// so only use this for a dashboard you run yourself, never on a public site.
const API_KEY = process.env.NEXT_PUBLIC_CONTROL_API_KEY || ''

export const api = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
api.interceptors.request.use(
  (config) => {
    if (API_KEY) {
      config.headers.set('X-API-Key', API_KEY)
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized
    }
    return Promise.reject(error)
  }
)

export default api

