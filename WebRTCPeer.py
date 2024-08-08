from logging import info
from typing import Callable, cast
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    RTCIceCandidate,
)


class WebRTCPeer:
    def __init__(self, ip: str | None):
        if ip is None:
            self._identifier = "[IP Not found]"
        else:
            self._identifier = ip

        self._pc = RTCPeerConnection()
        self._dataChannel: RTCDataChannel | None = None
        self._pc.on("datachannel", self.onDataChannel)
        self._pc.on("iceconnectionstatechange", self.onICEStateChange)
        self._pc.on("icecandidate", self.onICECandidate)

        self.onMessage = list[Callable[[str], None]]()
        self.onDisconnectCallbacks = list[Callable[[], None]]()
        self.onConnectCallbacks = list[Callable[[], None]]()
        self.onClosedCallbacks = list[Callable[[], None]]()

        self.closed = False
        self.connected = False
        self.sendBuffer = []

        pass

    async def initiateConnection(self, remoteDescription: RTCSessionDescription):
        await self._pc.setRemoteDescription(remoteDescription)
        answer = cast(RTCSessionDescription, await self._pc.createAnswer())

        await self._pc.setLocalDescription(answer)
        return self._pc.localDescription

    def send(self, message: str):
        if self._dataChannel is None:
            self.sendBuffer.append(message)
            return  # Might want to buffer instead

        self._dataChannel.send(message)

    async def onMessageReceived(self, message: str):
        if message == "CLOSE":
            await self.close()
            return

        print(message)

        for callback in self.onMessage:
            callback(message)

        pass

    def onReconnect(self):
        if self.connected:
            return

        self.connected = True
        for callback in self.onConnectCallbacks:
            callback()

    def onDisconnect(self):
        if not self.connected:
            return

        self.connected = False
        for callback in self.onDisconnectCallbacks:
            callback()

    def onDataChannel(self, channel: RTCDataChannel):
        self._dataChannel = channel
        print(f"ICE {self._identifier} data channel created")
        channel.on("message", self.onMessageReceived)
        for s in self.sendBuffer:
            channel.send(s)

        self.sendBuffer = []

    async def onICECandidate(self, candidate: RTCIceCandidate):
        print(f"new ice candidate {candidate}")
        await self._pc.addIceCandidate(candidate)

    async def onICEStateChange(self) -> None:
        print(
            f"ICE {self._identifier} connection"
            f"state is {self._pc.iceConnectionState}"
        )

        iceConnectionState = self._pc.iceConnectionState
        match iceConnectionState:
            case "completed":
                self.onReconnect()
            case "checking":
                self.onDisconnect()
            case "failed":
                self.onDisconnect()
                await self.close()
            case "closed":
                self.onClosed()

    async def close(self):
        if self.closed:
            return

        if self._dataChannel is not None:
            self._dataChannel.close()

        await self._pc.close()

    def onClosed(self):
        if self.closed:
            return

        if self.connected:
            self.onDisconnect()
            self.connected = False

        self.closed = True
        for callback in self.onClosedCallbacks:
            callback()
