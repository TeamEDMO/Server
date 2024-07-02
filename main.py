import asyncio

import EDMOSerial

async def main():
    serial = EDMOSerial.EDMOSerial()
    while(True):
        await serial.update()

if __name__ == "__main__":
    asyncio.run(main())
