/**
 * TeleLogin JavaScript Client
 * Simple client for browser-based authentication
 */

class TeleLoginClient {
  constructor(apiUrl = 'http://localhost:8000') {
    this.apiUrl = apiUrl;
    this.sessionToken = null;
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
   * @returns {Promise<boolean>} Login success
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
      return await this.pollLoginStatus(loginId, onStatusChange);
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  }

  /**
   * Poll login status
   * @param {string} loginId 
   * @param {Function} onStatusChange 
   * @returns {Promise<boolean>}
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
            resolve(true);
          } else if (['denied', 'expired'].includes(data.status)) {
            clearInterval(interval);
            resolve(false);
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
