"""
Python client example for TeleLogin
"""
import requests
import time

class TeleLoginClient:
    def __init__(self, api_url="http://localhost:8000"):
        self.api_url = api_url
        self.session_token = None
    
    def register(self, username):
        """Register a new user"""
        response = requests.post(
            f"{self.api_url}/register",
            json={"username": username}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"Registration link: {data['link']}")
            print("Please open this link in Telegram to complete registration")
            return data['link']
        else:
            print(f"Registration failed: {response.text}")
            return None
    
    def login(self, username, timeout=60):
        """Login with username and wait for Telegram confirmation"""
        # Start login
        response = requests.post(
            f"{self.api_url}/auth/start-login",
            json={"username": username}
        )
        
        if response.status_code != 200:
            print(f"Login failed: {response.text}")
            return False
        
        data = response.json()
        login_id = data['login_id']
        
        print(f"Login request sent. Check your Telegram for confirmation...")
        
        # Poll for status
        start_time = time.time()
        while time.time() - start_time < timeout:
            status_response = requests.get(f"{self.api_url}/status/{login_id}")
            
            if status_response.status_code == 200:
                status_data = status_response.json()
                
                if status_data['status'] == 'approved':
                    print("Login successful!")
                    # In a real implementation, you would receive the session token
                    # from the confirm-login endpoint
                    return True
                elif status_data['status'] in ['denied', 'expired']:
                    print(f"Login {status_data['status']}")
                    return False
            
            time.sleep(2)
        
        print("Login timeout")
        return False

# Example usage
if __name__ == "__main__":
    client = TeleLoginClient()
    
    # Register
    username = "testuser"
    # client.register(username)
    
    # Login
    client.login(username)
