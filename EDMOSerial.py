import asyncio
from curses import baudrate
from typing import Tuple
import serial
import serial_asyncio
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo
from serial_asyncio import SerialTransport

from Utilities.Bindable import Bindable

class SerialProtocol(asyncio.Protocol):
    closed = False
    identifier: str
    receivedData: list[bytes] = []
    identifying = False

    def connection_made(self, transport: SerialTransport):  # type: ignore
        self.transport = transport

        """transport.write(b"id")
        self.identifying = True"""
        print("port opened", transport)

    def data_received(self, data):
        if self.identifying:
            self.identifier = repr(data)
            if len(self.identifier) != "Bloom":
                self.transport.close()

            return

        print("data received", repr(data))
        self.receivedData.append(data)

    def connection_lost(self, exc):
        print("port closed")
        self.closed = True

    def pause_writing(self):
        print("pause writing")

    def resume_writing(self):
        print("resume writing")

    def pause_reading(self):
        # This will stop the callbacks to data_received
        self.transport.pause_reading()

    def resume_reading(self):
        # This will start the callbacks to data_received again with all data that has been received in the meantime.
        self.transport.resume_reading()

    def write(self, data: bytes):
        self.transport.write(data)


class EDMOSerial:
    connections: dict[str, Bindable[SerialProtocol]] = {}

    def __init__(self):
        pass

    async def update(self):
        await self.searchForConnections()
        await asyncio.sleep(1)

    async def searchForConnections(self):
        comports: list[ListPortInfo] = serial.tools.list_ports.comports(True)  # type: ignore

        for port in comports:
            if port.description == "Feather M0":
                await self.initializeConnection(port)
        pass

    async def initializeConnection(self, port: ListPortInfo):
        if port.device not in self.connections:
            self.connections[port.device] = Bindable[ SerialProtocol]()

        connectionBindable = self.connections[port.device]

        if (
            connectionBindable.hasValue()
            and not connectionBindable.getNonNullValue().closed # type: ignore
        ):
            return

        loop = asyncio.get_event_loop()
        transport, protocol = await serial_asyncio.create_serial_connection(
            loop, SerialProtocol, port.device, baudrate=9600
        )

        self.connections[port.device].set(protocol)

    async def onNewConnection(self):
        pass

    async def onConnectionLost(self):
        pass

    def write(self, id: str, data: bytes):
        for device in self.connections:

            connectionBindable = self.connections[device]
            if not connectionBindable.hasValue():
                return

            connection = connectionBindable.getNonNullValue()

            if connection.closed:
                continue

            if connection.identifier != id:
                continue

            connection.write(data)
