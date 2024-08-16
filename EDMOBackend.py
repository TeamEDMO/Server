# Handles everything

import asyncio
from aiohttp import web
from aiohttp.web_middlewares import normalize_path_middleware
from aiohttp_middlewares import cors_middleware  # type: ignore
from EDMOSession import EDMOSession
from FusedCommunication import FusedCommunication, FusedCommunicationProtocol
from aiortc.contrib.signaling import object_from_string, object_to_string

from aiortc import RTCSessionDescription

from WebRTCPeer import WebRTCPeer


# flake8: noqa: F811
class EDMOBackend:
    def __init__(self):
        self.activeEDMOs: dict[str, FusedCommunicationProtocol] = {}
        self.activeSessions: dict[str, EDMOSession] = {}

        self.fusedCommunication = FusedCommunication()
        self.fusedCommunication.onEdmoConnected.append(self.onEDMOConnected)
        self.fusedCommunication.onEdmoDisconnected.append(self.onEDMODisconnect)

        self.simpleViewEnabled = False

    # region EDMO MANAGEMENT

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

    # endregion

    # region SESSION MANAGEMENT

    def getEDMOSession(self, identifier):
        if identifier in self.activeSessions:
            return self.activeSessions[identifier]

        if identifier not in self.activeEDMOs:
            return None

        protocol = self.activeEDMOs[identifier]
        session = self.activeSessions[identifier] = EDMOSession(
            protocol, 4, self.removeSession
        )

        session.setSimpleView(self.simpleViewEnabled)

        return session

    def removeSession(self, session: EDMOSession):
        identifier = session.protocol.identifier
        if identifier in self.activeSessions:
            del self.activeSessions[identifier]

    # endregion

    async def onPlayerConnect(self, request: web.Request):
        """Attempts to handle a connecting player. Will establish a Websocket response if valid attempt."""
        """Otherwise it'll return 404 or 401 depending on what is wrong"""
        identifier = request.match_info["identifier"]

        if identifier not in self.activeEDMOs:
            return web.Response(status=404)

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue

            data = msg.json()

            username = data["playerName"]
            sessionDescription = object_from_string(data["handshake"])

            if isinstance(sessionDescription, RTCSessionDescription):
                player = WebRTCPeer(request.remote)

                session = self.getEDMOSession(identifier)

                if session is not None:
                    if not session.registerPlayer(player, username):
                        return web.Response(status=401)

                answer = await player.initiateConnection(sessionDescription)

                await ws.send_str(object_to_string(answer))

        return ws

    async def update(self):
        """Standard update loop to be performed at most 10 times a second"""
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

    # region ENDPOINT HANDLERS

    async def getActiveEDMOs(self, _: web.Request):
        edmos = [candidate for candidate in self.activeEDMOs]

        response = web.json_response(edmos)
        return response

    # This returns the available sessions and their capacities in a json list
    async def getActiveSessions(self, request: web.Request):
        return web.json_response(
            [self.activeSessions[s].getSessionInfo() for s in self.activeSessions]
        )

    async def getSessionInfo(self, request: web.Request) -> web.Response:
        identifier = request.match_info["identifier"]

        if identifier not in self.activeSessions:
            return web.Response(status=404)

        return web.json_response(self.activeSessions[identifier].getDetailedInfo())

    async def sendFeedback(self, request: web.Request) -> web.Response:
        identifier = request.match_info["identifier"]

        if identifier not in self.activeSessions:
            return web.Response(status=404)

        if not request.can_read_body:
            return web.Response(status=400)

        message = await request.text()
        self.activeSessions[identifier].sendFeedback(message)

        return web.Response(status=200)

    async def setTaskState(self, request: web.Request) -> web.Response:
        identifier = request.match_info["identifier"]

        if identifier not in self.activeSessions:
            return web.Response(status=404)

        if not request.can_read_body:
            return web.Response(status=400)

        message = await request.json()

        key = message.get("key")
        completed = message.get("completed")

        if not isinstance(key, str) or not isinstance(completed, bool):
            return web.Response(status=400)

        if not self.activeSessions[identifier].setTasks(key, completed):
            return web.Response(status=400)

        return web.Response(status=200)

    async def setHelpEnabled(self, request: web.Request):
        identifier = request.match_info["identifier"]

        if identifier not in self.activeSessions:
            return web.Response(status=404)

        if not request.can_read_body:
            return web.Response(status=400)

        message = await request.json()

        value = message.get("Value")

        if not isinstance(value, bool):
            return web.Response(status=400)

        self.activeSessions[identifier].setHelpEnabled(value)

        return web.Response(status=200)

    async def getSimpleView(self, request: web.Request):
        obj = {}
        obj["Value"] = self.simpleViewEnabled

        return web.json_response(obj)

    async def setSimpleView(self, request: web.Request):
        if not request.can_read_body:
            return web.Response(status=400)

        message = await request.json()
        value = message.get("Value")

        if not isinstance(value, bool):
            return web.Response(status=400)

        self.simpleViewEnabled = value

        for s in self.activeSessions:
            self.activeSessions[s].setSimpleView(value)

        return web.Response(status=200)

    # endregion

    async def run(self) -> None:
        app = web.Application(
            middlewares=[
                normalize_path_middleware(
                    remove_slash=True, merge_slashes=True, append_slash=False
                ),
                cors_middleware(allow_all=True),
            ]
        )

        app.router.add_route("GET", "/controller/{identifier}", self.onPlayerConnect)

        app.router.add_route("GET", "/edmos", self.getActiveEDMOs)
        app.router.add_route("GET", "/sessions", self.getActiveSessions)
        app.router.add_route("GET", "/sessions/{identifier}", self.getSessionInfo)

        app.router.add_route("PUT", "/simpleView", self.setSimpleView)
        app.router.add_route("GET", "/simpleView", self.getSimpleView)

        app.router.add_route(
            "PUT", "/sessions/{identifier}/helpEnabled", self.setHelpEnabled
        )

        app.router.add_route("PUT", "/sessions/{identifier}/tasks", self.setTaskState)

        app.router.add_route(
            "PUT", "/sessions/{identifier}/feedback", self.sendFeedback
        )

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

    async def onShutdown(self):
        """Shuts down existing connections gracefully to prevent a minor deadlock when shutting down the server"""
        self.fusedCommunication.close()
        for s in [sess for sess in self.activeSessions]:
            session = self.activeSessions[s]
            await session.close()
        pass


async def main():
    server = EDMOBackend()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
