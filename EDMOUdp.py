from asyncio import DatagramProtocol, DatagramTransport, get_event_loop
from datetime import datetime
from typing import Any, Callable, Optional

from Server.EDMOCommands import EDMOCommand, EDMOCommands, EDMOPacket


IPAddress = tuple[str | Any, int]


class UdpProtocol:
    def __init__(self, identifier: str, ip: IPAddress, transport: DatagramTransport):
        self.identifier = identifier
        self.lastResponseTime: datetime = datetime.now()
        self.ip = ip
        self.transport = transport

        self.onMessageReceived: Optional[Callable[[EDMOCommand], None]] = None

        pass

    def data_received(self, data):
        # print("UDP loopback: ", data)
        self.lastResponseTime = datetime.now()

        if self.onMessageReceived is not None:
            self.onMessageReceived(EDMOPacket.tryParse(data))

    def write(self, data: bytes):
        # print("UDP send: ", data)
        self.transport.sendto(data, self.ip)

    def isStale(self):
        return (datetime.now() - self.lastResponseTime).total_seconds() > 5

    pass


class EDMOUdp(DatagramProtocol):
    onConnect: list[Callable[[UdpProtocol], None]] = []
    onDisconnect: list[Callable[[UdpProtocol], None]] = []

    def __init__(self):
        self.transport: DatagramTransport
        self.peers: dict[IPAddress, UdpProtocol] = {}
        pass

    async def initialize(self):
        loop = get_event_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=("0.0.0.0", 2122),
            reuse_port=True,
            allow_broadcast=True,
        )

    async def update(self):
        self.searchForConnections()
        self.cleanUpStaleConnections()

    def searchForConnections(self):
        # Broadcast the id command to all peers
        # If an EDMO exist, we'll receive their identifier along with their IP
        self.transport.sendto(
            EDMOPacket.create(EDMOCommands.IDENTIFY), ("255.255.255.255", 2121)
        )

    # We want to ensure that if an EDMO doesn't respond
    #  (Due to shutdown, network fault, or Derrick's code)
    #  That we don't act as if nothing happenss
    def cleanUpStaleConnections(self):
        staleConnections = [p for p in self.peers if self.peers[p].isStale()]

        for p in staleConnections:
            print("Cleaned up port ", p)
            protocol = self.peers[p]
            del self.peers[p]

            for callback in self.onDisconnect:
                callback(protocol)

    def connection_made(self, transport):
        self.transport = transport
        # We actually don't really care about this

    def datagram_received(self, data: bytes, addr):
        # Received the identifier, potentially replying to a broadcast
        command = EDMOPacket.tryParse(data)

        if addr not in self.peers:
            if command.Instruction == EDMOCommands.IDENTIFY:
                identifier = command.Data.decode()
                udpProto = UdpProtocol(identifier, addr, self.transport)
                self.peers[addr] = udpProto

                self.onConnectionEstablished(udpProto)

            return

        self.peers[addr].data_received(data)
        pass

    def onConnectionEstablished(self, protocol: UdpProtocol):

        # Notify subscribers of the change
        for callback in self.onConnect:
            callback(protocol)

    def close(self):
        self.transport.close()
