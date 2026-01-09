import asyncio
import logging

from .config import Settings
from .bridge.core import Bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


async def main():
    settings = Settings()
    bridge = Bridge(settings)
    await bridge.start()


if __name__ == "__main__":
    asyncio.run(main())
