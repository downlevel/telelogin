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
    return this.sessionToken;
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
  logout() {
    this.setToken(null);
  }

  /**
   * Make authenticated API request
   * @param {string} endpoint 
   * @param {object} options Fetch options
   * @returns {Promise<Response>}
   */
  async authenticatedRequest(endpoint, options = {}) {
    if (!this.sessionToken) {
      throw new Error('Not authenticated. Please login first.');
    }

    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.sessionToken}`,
      ...(options.headers || {})
    };

    return fetch(`${this.apiUrl}${endpoint}`, {
      ...options,
      headers
    });
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
      console.log('Registration link:', data.link);
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
  async login(username, onStatusChange = null) {
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

      if (onStatusChange) {
        onStatusChange('pending');
      }

      // Poll for status
      const result = await this.pollLoginStatus(loginId, onStatusChange);
      
      // Store token if login successful
      if (result.success && result.sessionToken) {
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
  async pollLoginStatus(loginId, onStatusChange = null, timeout = 60000) {
    const startTime = Date.now();
    const pollInterval = 2000;

    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        try {
          const response = await fetch(`${this.apiUrl}/status/${loginId}`);
          
          if (!response.ok) {
            clearInterval(interval);
            reject(new Error('Status check failed'));
            return;
          }

          const data = await response.json();

          if (onStatusChange) {
            onStatusChange(data.status);
          }

          if (data.status === 'approved') {
            clearInterval(interval);
            
            // Fetch the session token from the login request
            // Note: In the current implementation, the token is returned when confirming
            // Since we're polling status, we need to get it from the confirmed login
            // For now, we'll need to modify the API to return the token in status
            // Or store it when login is approved
            
            resolve({
              success: true,
              status: 'approved',
              sessionToken: data.session_token || null
            });
          } else if (['denied', 'expired'].includes(data.status)) {
            clearInterval(interval);
            resolve({
              success: false,
              status: data.status
            });
          }

          // Check timeout
          if (Date.now() - startTime > timeout) {
            clearInterval(interval);
            reject(new Error('Login timeout'));
          }
        } catch (error) {
          clearInterval(interval);
          reject(error);
        }
      }, pollInterval);
    });
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
