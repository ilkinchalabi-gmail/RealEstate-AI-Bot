# Bot package initialization
import sys
import os

# bot/ qovluğunu sys.path-ə əlavə et ki,
# "python -m bot.main" ilə çağırıldıqda "from config import ..." işləsin
_bot_dir = os.path.dirname(os.path.abspath(__file__))
if _bot_dir not in sys.path:
    sys.path.insert(0, _bot_dir)
