import asyncio
from datetime import datetime, timedelta
import pytz
from app.workpace_client import workpace_client
from app.config import settings

async def main():
    TZ = pytz.timezone(settings.timezone)
    now = datetime.now(TZ)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc).replace(tzinfo=None)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(pytz.utc).replace(tzinfo=None)
    
    data = await workpace_client.get_timetable_span(start, end, take=5)
    print("Response Data:", data.get("data", [])[:2])

asyncio.run(main())
