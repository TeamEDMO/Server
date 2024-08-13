from asyncio import create_task
import asyncio
from typing import Callable, Optional
from EDMOCommands import EDMOCommand
from EDMOSerial import EDMOSerial, SerialProtocol
from EDMOUdp import EDMOUdp, UdpProtocol


class FusedCommunicationProtocol:
    """This class is a wrapper protocol that holds one or more communication protocols to the same EDMO, serving as a simple router"""
    """If both serial and UDP communication protocols are established, Serial will be preferred for communication"""

    def __init__(self, identifier: str):
        self.serialCommunication: Optional[SerialProtocol] = None
        self.udpCommunication: Optional[UdpProtocol] = None
        self.identifier = identifier

        self.onMessageReceived: Optional[Callable[[EDMOCommand], None]] = None
        self.onConnectionEstablished: Optional[Callable[[], None]] = None

        self.connected = False

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
        hasPreviousConnection = self.hasConnection()

        if isinstance(protocol, SerialProtocol):
            self.serialCommunication = protocol
        elif isinstance(protocol, UdpProtocol):
            self.udpCommunication = protocol
        else:
            raise TypeError("Only serial or UDP protocol is accepted")

        protocol.onMessageReceived = self.messageReceived
        self.connected = self.hasConnection()

        if not hasPreviousConnection and self.connected:
            if self.onConnectionEstablished is not None:
                self.onConnectionEstablished()

    def unbind(self, protocol: SerialProtocol | UdpProtocol):
        if protocol == self.serialCommunication:
            self.serialCommunication = None
        elif protocol == self.udpCommunication:
            self.udpCommunication = None
        else:
            return

        protocol.onMessageReceived = None
        self.connected = self.hasConnection()

    def messageReceived(self, command: EDMOCommand):
        if self.onMessageReceived is not None:
            self.onMessageReceived(command)

    def hasConnection(self):
        return self.serialCommunication is not None or self.udpCommunication is not None


class FusedCommunication:
    """This class is the central management class for all supported communication methods"""

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
        self.connections[identifier] = fusedProto
        return fusedProto

    def onConnect(self, protocol: SerialProtocol | UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)

        previouslyConnected = fused.hasConnection()

        fused.bind(protocol)

        if not previouslyConnected:
            self.edmoConnected(fused)

    def onDisconnect(self, protocol: SerialProtocol | UdpProtocol):
        fused = self.getFusedConnectionFor(protocol.identifier)

        fused.unbind(protocol)

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
