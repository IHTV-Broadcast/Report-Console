import os
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Bot settings
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # Your chat ID for receiving reports

# Gemini settings
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# List of servers
SERVERS = [
    "Farsi",
    "Arabic",
    "English",
    "Urdu",
    "Turki",
    "Live",
    "Other",
    # Add more servers as needed
]

# Problem categories
PROBLEM_CATEGORIES = [
    "Broadcast",
    "Conductor",
    "Social Media",
    "Archive"
]

# Problem subcategories by category
PROBLEM_SUBCATEGORIES = {
    # Conductor issues
    "Conductor": [
        "Excels and Playlists",
        "Import",
        "Internet",
        "Channel Managers",
        "Other"
    ],
    
    # Social Media issues
    "Social Media": [
        "Social Media Server",
        "CastR Server",
        "Internet",
        "Platforms",
        "Other"
    ],
    
    # مشکلات آرشیو
    "Archive": [
        "Internet",
        "Automations",
        "Personnales/Managers",
        "Excels and datasheets",
        "Other"
    ],
    
    # مشکلات پخش
    "Broadcast": [
        "Live Streams",
        "Servers",
        "Internet and Connection",
        "Playlists and Transfers",
        "Other"
    ],
}

# For backward compatibility
PROBLEM_TYPES = PROBLEM_CATEGORIES

# Work sections
WORK_SECTIONS = [
    "Live",
    "Archive",
    "Conductor",
    "Social Media",
    "Playlist",
    "Monitoring",
    "Support"
]

# Live event sources
LIVE_EVENT_SOURCES = [
    "Controls",
    "Servers",
    "Internet",
    "Other"
]