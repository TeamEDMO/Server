import asyncio
from aiohttp import web

from EDMOSession import EDMOSession
from FusedCommunication import FusedCommunication, FusedCommunicationProtocol
from aiortc.contrib.signaling import object_from_string, object_to_string

from aiortc import RTCSessionDescription

from WebRTCPeer import WebRTCPeer

class EDMOBackend:
    def __init__(self):
        self.activeEDMOs: dict[str, FusedCommunicationProtocol] = {}
        self.activeSessions: dict[str, EDMOSession] = {}

        self.fusedCommunication = FusedCommunication()
        self.fusedCommunication.onEdmoConnected.append(self.onEDMOConnected)
        self.fusedCommunication.onEdmoDisconnected.append(self.onEDMODisconnect)

    def onEDMOConnected(self, protocol: FusedCommunicationProtocol):
        # Assumption: protocol is non null
        identifier = protocol.identifier
        self.activeEDMOs[identifier] = protocol

    def onEDMODisconnect(self, protocol: FusedCommunicationProtocol):
        # Assumption: protocol is non null
        identifier = protocol.identifier

        # Remove session from candidates
        if identifier in self.activeEDMOs:
            del self.activeEDMOs[identifier]

    def getEDMOSession(self, identifier):
        if identifier in self.activeSessions:
            return self.activeSessions[identifier]

        if identifier not in self.activeEDMOs:
            return None

        protocol = self.activeEDMOs[identifier]
        session = self.activeSessions[identifier] = EDMOSession(
            protocol, 4, self.removeSession
        )

        return session

    def removeSession(self, session: EDMOSession):
        identifier = session.protocol.identifier
        if identifier in self.activeSessions:
            del self.activeSessions[identifier]

    async def onShutdown(self):
        self.fusedCommunication.close()
        pass

    async def onPlayerConnect(self, request: web.Request):
        identifier = request.match_info["identifier"]

        if identifier not in self.activeEDMOs:
            return web.Response(status=404)

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            print(msg)
            if msg.type == web.WSMsgType.TEXT:
                data = object_from_string(msg.data)
                # we are only looking for one thing from the websocket
                if isinstance(data, RTCSessionDescription):
                    player = WebRTCPeer(request.remote)

                    answer = await player.initiateConnection(data)

                    await ws.send_str(object_to_string(answer))

                    session = self.getEDMOSession(identifier)

                    if session is not None:
                        session.registerPlayer(player)

        return ws

    # This returns the available sessions and their capacities in a json list
    async def getActiveSessions(self, request: web.Request):
        sessions = []
        for candidateSession in self.activeSessions:
            sessionInfo = {}
            sessionInfo["identifier"] = candidateSession

            edmoSession = self.activeSessions[candidateSession]

            sessionInfo["activePlayers"] = len(edmoSession.activePlayers)
            sessionInfo["MaxPlayers"] = len(edmoSession.motors)

            sessions.append(sessionInfo)

        response = web.json_response(sessions)
        return response

    async def getActiveEDMOs(self, request: web.Request):
        edmos = [candidate for candidate in self.activeEDMOs]

        response = web.json_response(edmos)
        return response

    async def shutdown(self, request: web.Request):
        print("Shutting down gracefully...")
        raise web.GracefulExit()

    async def update(self):
        # Update the serial stuff
        serialUpdateTask = asyncio.create_task(self.fusedCommunication.update())

        # Update all sessions
        sessionUpdates = []

        for sessionID in self.activeSessions:
            session = self.activeSessions[sessionID]
            sessionUpdates.append(asyncio.create_task(session.update()))

        # Ensure that the update cycle runs at most 10 times a second
        minUpdateDuration = asyncio.create_task(asyncio.sleep(0.1))

        await serialUpdateTask
        if len(sessionUpdates) > 0:
            await asyncio.wait(sessionUpdates)
        await minUpdateDuration

    async def run(self) -> None:
        app = web.Application()
        # app.on_shutdown.append(self.onShutdown)
        app.router.add_route("GET", "/controller/{identifier}", self.onPlayerConnect)
        app.router.add_route("GET", "/activeSessions", self.getActiveSessions)
        app.router.add_route("GET", "/activeEdmos", self.getActiveEDMOs)

        runner = web.AppRunner(app)
        await runner.setup()
        runner.shutdown_callback = self.onShutdown

        site = web.TCPSite(runner, port=8080)
        await site.start()

        await self.fusedCommunication.initialize()

        closed = False

        try:
            while not closed:
                await self.update()
        except (asyncio.exceptions.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await runner.cleanup()


async def main():
    server = EDMOBackend()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
