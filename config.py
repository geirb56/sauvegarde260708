# Centralized Configuration

import os

# Environment Variables
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_USER = os.getenv('DB_USER', 'user')
DB_PASS = os.getenv('DB_PASS', 'password')

# Constants
TIMEOUT = 30
RETRIES = 3
BASE_URL = 'https://api.example.com'