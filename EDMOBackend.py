import asyncio
from aiohttp import web

from EDMOSerial import EDMOSerial, SerialProtocol
from EDMOSession import EDMOSession
from Utilities.Bindable import Bindable


class EDMOBackend:
    def __init__(self):
        self.candidateSessions: dict[str, EDMOSession] = {}
        self.allSessions: dict[str, EDMOSession] = {}
        self.edmoSerial = EDMOSerial()
        pass

    def onEDMOConnected(self, protocolBindable: Bindable[SerialProtocol]):
        # Assumption: protocol is non null
        protocol = protocolBindable.getNonNullValue()
        identifier = protocol.identifier

        if identifier in self.allSessions:
            # Move to valid candidate session
            self.candidateSessions[identifier] = self.allSessions[identifier]
        else:
            newSession = EDMOSession(protocolBindable, 4)
            self.allSessions[identifier] = newSession
            self.candidateSessions[identifier] = newSession

    def onEDMODisconnect(self, protocolBindable: Bindable[SerialProtocol]):
        # Assumption: protocol is non null
        protocol = protocolBindable.getNonNullValue()
        identifier = protocol.identifier

        # Remove session from candidates
        if identifier in self.candidateSessions:
            del self.candidateSessions[identifier]

        # We don't remove it from all sessions just yet
        # This is because the connection may be reestablished
        #  and we want to allow a seamless recovery for existing users

    async def onShutdown(self, app: web.Application):
        pass

    async def onConnect(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str("test")

        print("something happened")

        return ws

    async def update(self):
        # Update the serial stuff
        serialUpdateTask = asyncio.create_task(self.edmoSerial.update())

        # Ensure that the update cycle runs at most 10 times a second
        minUpdateDuration = asyncio.create_task(asyncio.sleep(0.1))

        await serialUpdateTask
        await minUpdateDuration

    async def run(self) -> None:
        app = web.Application()
        app.on_shutdown.append(self.onShutdown)
        app.router.add_route("GET", "/", self.onConnect)

        web.run_app

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "localhost", 8080)
        await site.start()

        closed = False

        try:
            while not closed:
                await self.update()
        except (asyncio.exceptions.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await site.stop()
            await runner.cleanup()


async def main():
    server = EDMOBackend()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
