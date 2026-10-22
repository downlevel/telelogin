/**
 * TeleLogin JavaScript Client
 * Simple client for browser-based authentication
 */

class TeleLoginClient {
  constructor(apiUrl = 'http://localhost:8000', storage = 'localStorage') {
    this.apiUrl = apiUrl;
    this.storage = storage === 'sessionStorage' ? sessionStorage : localStorage;
    this.storageKey = 'telelogin_session_token';
    
    // Load existing token from storage
    this.sessionToken = this.storage.getItem(this.storageKey);
  }

  /**
   * Get current session token
   * @returns {string|null}
   */
  getToken() {
    return this.storage.getItem(this.storageKey);
  }

  /**
   * Set session token
   * @param {string} token 
   */
  setToken(token) {
    this.sessionToken = token;
    if (token) {
      this.storage.setItem(this.storageKey, token);
    } else {
      this.storage.removeItem(this.storageKey);
    }
  }

  /**
   * Check if user is authenticated
   * @returns {boolean}
   */
  isAuthenticated() {
    return !!this.sessionToken;
  }

  /**
   * Logout user
   */
  setRefreshToken(token) {
    if (token) this.storage.setItem('telelogin_refresh_token', token);
    else this.storage.removeItem('telelogin_refresh_token');
  }

  async refresh(failedToken = this.getToken()) {
    if (this.refreshPromise) return this.refreshPromise;
    const run = async () => {
      const current = this.storage.getItem(this.storageKey);
      if (current && current !== failedToken) {
        this.sessionToken = current;
        return;
      }
      const refreshToken = this.storage.getItem('telelogin_refresh_token');
      if (!refreshToken) {
        // Nothing to refresh with (legacy login or cleared by another tab)
        this.setToken(null);
        throw new Error('Refresh failed');
      }
      const response = await fetch(`${this.apiUrl}/auth/refresh`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({refresh_token: refreshToken})
      });
      if (response.status >= 400 && response.status < 500) {
        this.setToken(null);
        this.setRefreshToken(null);
      }
      if (!response.ok) throw new Error('Refresh failed');
      const data = await response.json();
      this.setRefreshToken(data.refresh_token);
      this.setToken(data.session_token);
    };
    this.refreshPromise = (async () => {
      if (typeof navigator !== 'undefined' && navigator.locks) {
        await navigator.locks.request('telelogin-refresh', run);
      } else await run();
    })();
    try { await this.refreshPromise; }
    finally { this.refreshPromise = null; }
  }

  async me() {
    const response = await this.authenticatedRequest('/auth/me');
    if (!response.ok) throw new Error('Authentication failed');
    return response.json();
  }

  async logout() { return this.endSession('/auth/logout'); }
  async logoutAll() { return this.endSession('/auth/logout-all'); }
  async endSession(endpoint) {
    try {
      const response = await this.authenticatedRequest(endpoint, {method:'POST'});
      if (!response.ok) throw new Error('Logout failed');
      return await response.json();
    } finally {
      this.setToken(null);
      this.setRefreshToken(null);
    }
  }

  async authenticatedRequest(endpoint, options = {}) {
    const token = this.storage.getItem(this.storageKey);
    if (!token) throw new Error('Not authenticated. Please login first.');
    const send = (access) => fetch(`${this.apiUrl}${endpoint}`, {
      ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {}), Authorization: `Bearer ${access}`}
    });
    const response = await send(token);
    if (response.status !== 401) return response;
    await this.refresh(token);
    return send(this.getToken());
  }

  /**
   * Register a new user
   * @param {string} username 
   * @returns {Promise<string>} Registration link
   */
  async register(username) {
    try {
      const response = await fetch(`${this.apiUrl}/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username }),
      });

      if (!response.ok) {
        throw new Error(`Registration failed: ${response.statusText}`);
      }

      const data = await response.json();
      return data.link;
    } catch (error) {
      console.error('Registration error:', error);
      throw error;
    }
  }

  /**
   * Start login process
   * @param {string} username 
   * @param {Function} onStatusChange Callback for status updates
   * @returns {Promise<object>} Login result with success flag and token
   */
  async login(username, onStatusChange = null, onCode = null) {
    try {
      // Start login
      const response = await fetch(`${this.apiUrl}/auth/start-login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username }),
      });

      if (!response.ok) {
        throw new Error(`Login failed: ${response.statusText}`);
      }

      const data = await response.json();
      const loginId = data.login_id;
      if (onCode) onCode(data.verification_code);

      if (onStatusChange) {
        onStatusChange('pending');
      }

      // Poll for status
      const result = await this.pollLoginStatus(loginId, onStatusChange);
      
      // Store token if login successful
      if (result.success && result.sessionToken) {
        this.setRefreshToken(result.refreshToken);
        this.setToken(result.sessionToken);
      }
      
      return result;
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  }

  /**
   * Poll login status
   * @param {string} loginId 
   * @param {Function} onStatusChange 
   * @returns {Promise<object>} Login result with status and session_token
   */
  async pollLoginStatus(loginId, onStatusChange = null, timeout = 150000) {
    const startTime = Date.now();
    const pollInterval = 2000;
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    const remaining = () => timeout - (Date.now() - startTime);

    // One request at a time: the session token is delivered only once,
    // so overlapping polls could let a token-less response win the race.
    while (remaining() > pollInterval) {
      await sleep(pollInterval);

      // Bound each request (and its body) by the overall deadline
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), remaining());
      let data;
      try {
        const response = await fetch(`${this.apiUrl}/auth/status`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({login_id: loginId}), signal: controller.signal });
        if (!response.ok) {
          throw new Error('Status check failed');
        }
        data = await response.json();
      } catch (error) {
        if (error.name === 'AbortError') {
          throw new Error('Login timeout');
        }
        throw error;
      } finally {
        clearTimeout(timer);
      }

      if (onStatusChange) {
        onStatusChange(data.status);
      }

      if (data.status === 'approved') {
        if (!data.session_token) {
          // Token already delivered to another poll of this login
          return {
            success: false,
            status: 'approved',
            error: 'Session token already retrieved'
          };
        }
        return {
          success: true,
          status: 'approved',
          sessionToken: data.session_token,
          refreshToken: data.refresh_token
        };
      }

      if (['denied', 'expired'].includes(data.status)) {
        return {
          success: false,
          status: data.status
        };
      }
    }

    throw new Error('Login timeout');
  }
}

// Export for Node.js or browser
if (typeof module !== 'undefined' && module.exports) {
  module.exports = TeleLoginClient;
}

// Example usage:
/*
const client = new TeleLoginClient('http://localhost:8000', 'localStorage');

// Register
async function register() {
  const link = await client.register('myusername');
  console.log('Open this link in Telegram:', link);
}

// Login
async function login() {
  const result = await client.login('myusername', (status) => {
    console.log('Login status:', status);
  });
  
  if (result.success) {
    console.log('Login successful! Token:', client.getToken());
    // Now you can make authenticated requests
    const response = await client.authenticatedRequest('/some-protected-endpoint');
  } else {
    console.log('Login failed:', result.status);
  }
}

// Check if already logged in
if (client.isAuthenticated()) {
  console.log('Already logged in with token:', client.getToken());
}

// Logout
client.logout();
*/
