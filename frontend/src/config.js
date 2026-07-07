/**
 * Application Configuration
 * Centralized config with fallbacks and validation
 */

// Get backend URL with fallback
const getBackendUrl = () => {
  const url = process.env.REACT_APP_BACKEND_URL;
  
  // Development fallback
  if (!url || url === 'undefined') {
    console.warn('⚠️ REACT_APP_BACKEND_URL not found in environment. Using fallback.');
    // Try to detect the current domain
    if (typeof window !== 'undefined') {
      return window.location.origin;
    }
    return 'http://localhost:3000';
  }
  
  return url;
};

export const BACKEND_URL = getBackendUrl();
export const API_BASE_URL = `${BACKEND_URL}/api`;

// Log configuration in development
if (process.env.NODE_ENV === 'development') {
  console.log('🔧 App Configuration:', {
    BACKEND_URL,
    API_BASE_URL,
    NODE_ENV: process.env.NODE_ENV,
  });
}

export default {
  BACKEND_URL,
  API_BASE_URL,
};
