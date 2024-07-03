import asyncio
from typing import Callable, cast
import serial
import serial_asyncio
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo
from serial.tools.list_ports import comports
from serial_asyncio import SerialTransport
from typing import Self
from Utilities.Bindable import Bindable


class SerialProtocol(asyncio.Protocol):
    def __init__(self):
        self.connectionCallbacks = list[Callable[[Self], None]]()
        self.disconnectCallbacks = list[Callable[[Self], None]]()
        self.identifying = False
        self.receivedData = list[bytes]()
        self.identifier = "AAAA"
        self.closed = False
        self.device = ""

    def connection_made(self, transport: SerialTransport):  # type: ignore
        self.transport = transport

        """transport.write(b"id")
        self.identifying = True"""

        self.identifier = self.device

        for callback in self.connectionCallbacks:
            callback(self)

        print("port opened", transport)

    def data_received(self, data):
        if self.identifying:
            self.identifier = repr(data)
            if len(self.identifier) != "Bloom":
                self.transport.close()

            return

        # print("data received", repr(data))
        self.receivedData.append(data)

    def connection_lost(self, exc):
        for callback in self.disconnectCallbacks:
            callback(self)

        print("port closed")
        self.closed = True

    def pause_writing(self):
        print("pause writing")

    def resume_writing(self):
        print("resume writing")

    def pause_reading(self):
        self.transport.pause_reading()

    def resume_reading(self):
        self.transport.resume_reading()

    def write(self, data: bytes):
        self.transport.write(data)

    def close(self):
        self.transport.close()


class EDMOSerial:
    connections: dict[str, Bindable[SerialProtocol]] = {}
    devices: dict[str, SerialProtocol] = {}

    onConnect: list[Callable[[Bindable[SerialProtocol]], None]] = []
    onDisconnect: list[Callable[[Bindable[SerialProtocol]], None]] = []

    def __init__(self):
        pass

    async def update(self):
        await self.searchForConnections()

    async def searchForConnections(self):
        ports: list[ListPortInfo] = comports(True)  # type: ignore

        connectionTasks = []

        for port in ports:
            # We only care about M0's at the moment
            # This can be expanded if we ever use other boards
            if port.description == "Feather M0":
                connectionTasks.append(
                    asyncio.create_task(self.initializeConnection(port))
                )

        if len(connectionTasks) > 0:
            await asyncio.wait(connectionTasks)

    async def initializeConnection(self, port: ListPortInfo):
        # This device is still being used, we don't need to init
        if port.device in self.devices:
            return

        # This creates a serial connection for the port
        # The port will run asynchorously in the background
        # SerialProtocol contains the general management code
        loop = asyncio.get_event_loop()
        _, protocol = await serial_asyncio.create_serial_connection(
            loop, SerialProtocol, port.device, baudrate=9600
        )

        # For typing purposes, no actual effect
        serialProtocol = cast(SerialProtocol, protocol)

        # We need to keep track of the device used
        #  so we don't create a new connection later
        serialProtocol.device = port.device
        self.devices[port.device] = serialProtocol

        serialProtocol.disconnectCallbacks.append(self.onConnectionLost)
        serialProtocol.connectionCallbacks.append(self.onConnectionEstablished)

    def onConnectionEstablished(self, protocol: SerialProtocol):
        # We either already seen this identifier, or we haven't
        # We try to reuse the bindable so sessions automatically update
        if protocol.identifier in self.connections:
            connectionBindable = self.connections[protocol.identifier]
        else:
            connectionBindable = Bindable[SerialProtocol]()
            self.connections[protocol.identifier] = connectionBindable

        connectionBindable.set(protocol)

        # Notify subscribers of the change
        for callback in self.onConnect:
            callback(connectionBindable)

    def onConnectionLost(self, protocol: SerialProtocol):
        # We remove the device from the list

        del self.devices[protocol.device]

        connectionBindable = self.connections[protocol.identifier]

        # Notify subscribers of the change
        # We do this *BEFORE* setting the bindable to none
        # This is to ensure that receivers knows which protocol is lost
        for callback in self.onDisconnect:
            callback(connectionBindable)

        connectionBindable.set(None)

    def close(self):
        devices = self.devices.copy()
        for device in devices:
            devices[device].close()
