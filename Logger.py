from datetime import datetime
import aiofiles
import os


class SessionLogger:
    def __init__(self, name: str):
        self.name = name
        self.channels = dict[str, list[str]]()
        self.sessionStartTime = datetime.now()
        self.lastFlushTime = self.sessionStartTime
        path = self.directoryName = f"./SessionLogs/{self.sessionStartTime.strftime(f"%Y.%m.%d/{self.name}/%H.%M.%S")}"

        if not os.path.exists(path):
            os.makedirs(path)

        pass

    def write(self, channel: str, message: str):
        if channel not in self.channels:
            self.channels[channel] = []

        sessionTime = datetime.now() - self.sessionStartTime
        self.channels[channel].append(f"{str(sessionTime)}: {message}\n")
        pass

    async def flush(self):
        for channel in self.channels:
            channelContent = self.channels[channel]

            if len(channelContent) == 0:
                continue

            async with aiofiles.open(
                f"{self.directoryName}/{channel}.log", "a+"
            ) as log:
                await log.writelines(channelContent)

            channelContent.clear()

    async def update(self):
        deltaTime = (datetime.now() - self.sessionStartTime).total_seconds()

        # Let's not constantly write to file
        if deltaTime < 5:
            return

        await self.flush()

    pass
