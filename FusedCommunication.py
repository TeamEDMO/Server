from asyncio import create_task
import asyncio
from typing import Callable, Optional

from serial import protocol_handler_packages

from EDMOSerial import EDMOSerial, SerialProtocol
from EDMOUdp import EDMOUdp, UdpProtocol


class FusedCommunicationProtocol:
    def __init__(self, identifier: str):
        self.serialCommunication: Optional[SerialProtocol] = None
        self.udpCommunication: Optional[UdpProtocol] = None
        self.identifier = identifier

        self.onMessageReceived: Optional[Callable[[bytes], None]] = None

        pass

    def write(self, message: bytes):
        # Prioritize serial communication if present
        if self.serialCommunication is not None:
            self.serialCommunication.write(message)
            return

        if self.udpCommunication is not None:
            self.udpCommunication.write(message)
            return

    def bind(self, protocol: SerialProtocol | UdpProtocol):
        if isinstance(protocol, SerialProtocol):
            self.serialCommunication = protocol
        elif isinstance(protocol, UdpProtocol):
            self.udpCommunication = protocol
        else:
            raise TypeError("Only serial or UDP protocol is accepted")

        protocol.onMessageReceived = self.messageReceived

    def unbind(self, protocol: SerialProtocol | UdpProtocol):
        if protocol == self.serialCommunication:
            self.serialCommunication = None
        elif protocol == self.udpCommunication:
            self.udpCommunication = None
        else:
            return

        protocol.onMessageReceived = None

    def messageReceived(self, message: bytes):
        if self.onMessageReceived is not None:
            self.onMessageReceived(message)

    def hasConnection(self):
        return self.serialCommunication is not None or self.udpCommunication is not None


class FusedCommunication:
    def __init__(self):
        self.connections: dict[str, FusedCommunicationProtocol] = {}

        serial = self.serial = EDMOSerial()
        serial.onConnect.append(self.onConnect)
        serial.onDisconnect.append(self.onDisconnect)

        udp = self.udp = EDMOUdp()
        udp.onConnect.append(self.onConnect)
        udp.onDisconnect.append(self.onDisconnect)

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

    def onConnect(self, protocol: SerialProtocol | UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)

        previouslyConnected = fused.hasConnection()

        fused.bind(protocol)

        if not previouslyConnected:
            self.edmoConnected(fused)

    def onDisconnect(self, protocol: SerialProtocol | UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)
        fused.serialCommunication = None

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
