# Telegram Bot Token
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# Your User ID, you can get it from @userinfobot
OWNER_ID = "YOUR_TELEGRAM_USER_ID"

# Wallet for payments (e.g., USDT TRC-20)
PAYMENT_WALLET = "YOUR_USDT_TRC20_WALLET_ADDRESS"

# Blockchain explorer API settings
# For Tron (TRC-20), you can use TronGrid or any other public API
# No API key is required for some public endpoints, but it's better to get one if possible
TRONGRID_API_URL = "https://api.trongrid.io"
# It's recommended to get an API key from a provider for better reliability
TRONGRID_API_KEY = "YOUR_TRONGRID_API_KEY"  # Optional, but recommended

# Database file
DB_FILE = "bot_database.db"

# Time in minutes to check for recent transactions
TRANSACTION_CONFIRMATION_WINDOW = 30

# How many days before expiration to send a reminder
RENEWAL_REMINDER_DAYS = 3
