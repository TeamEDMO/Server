from asyncio import create_task
import asyncio
from typing import Callable, Optional

from EDMOSerial import EDMOSerial, SerialProtocol
from EDMOUdp import EDMOUdp, UdpProtocol


class FusedCommunicationProtocol:
    def __init__(self, identifier: str):
        self.serialCommunication: Optional[SerialProtocol] = None
        self.udpCommunication: Optional[UdpProtocol] = None
        self.identifier = identifier
        pass

    def write(self, message: bytes):
        # Prioritize serial communication if present
        if self.serialCommunication is not None:
            self.serialCommunication.write(message)
            return

        if self.udpCommunication is not None:
            self.udpCommunication.write(message)
            return

    def hasConnection(self):
        return self.serialCommunication is not None or self.udpCommunication is not None


class FusedCommunication:
    def __init__(self):
        self.connections: dict[str, FusedCommunicationProtocol] = {}

        serial = self.serial = EDMOSerial()
        serial.onConnect.append(self.onSerialConnect)
        serial.onDisconnect.append(self.onSerialDisconnect)

        udp = self.udp = EDMOUdp()
        udp.onConnect.append(self.onUDPConnect)
        udp.onDisconnect.append(self.onUDPDisconnect)

        self.onEdmoConnected = list[Callable[[FusedCommunicationProtocol], None]]()
        self.onEdmoDisconnected = list[Callable[[FusedCommunicationProtocol], None]]()

    async def initialize(self):
        await self.udp.initialize()
        pass

    async def update(self):
        serialUpdateTask = create_task(self.serial.update())
        udpUpdateTask = create_task(self.udp.update())

        await asyncio.wait([serialUpdateTask, udpUpdateTask])

    def getFusedConnectionFor(self, identifier: str):
        if identifier in self.connections:
            return self.connections[identifier]

        fusedProto = FusedCommunicationProtocol(identifier)
        self.connections[identifier] = FusedCommunicationProtocol(identifier)
        return fusedProto

    def onSerialConnect(self, protocol: SerialProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)

        previouslyConnected = fused.hasConnection()

        fused.serialCommunication = protocol

        if not previouslyConnected:
            self.edmoConnected(fused)

    def onSerialDisconnect(self, protocol: SerialProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)
        fused.serialCommunication = None

        if not fused.hasConnection():
            self.edmoDisconnected(fused)

    def onUDPConnect(self, protocol: UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)

        previouslyConnected = fused.hasConnection()

        fused.udpCommunication = protocol

        if not previouslyConnected:
            self.edmoConnected(fused)

    def onUDPDisconnect(self, protocol: UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)
        fused.udpCommunication = None

        if not fused.hasConnection():
            self.edmoDisconnected(fused)

    def edmoConnected(self, protocol: FusedCommunicationProtocol):
        for c in self.onEdmoConnected:
            c(protocol)

    def edmoDisconnected(self, protocol: FusedCommunicationProtocol):
        for c in self.onEdmoDisconnected:
            c(protocol)

    def close(self):
        self.serial.close()
        self.udp.close()
