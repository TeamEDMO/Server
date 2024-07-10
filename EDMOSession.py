# Holds 1 session to be used with 1 robot

from collections import deque
from typing import TYPE_CHECKING

from EDMOMotor import EDMOMotor
from EDMOSerial import SerialProtocol
from Utilities.Bindable import Bindable
from Utilities.Helpers import removeIfExist
from WebRTCPeer import WebRTCPeer

if TYPE_CHECKING:
    from EDMOSession import EDMOSession


class EDMOPlayer:
    def __init__(self, rtcPeer: WebRTCPeer, edmoSession: "EDMOSession"):
        self.rtc = rtcPeer
        self.session = edmoSession
        self.number = -1
        rtcPeer.onMessage.append(self.onMessage)
        rtcPeer.onConnectCallbacks.append(self.onConnect)
        rtcPeer.onDisconnectCallbacks.append(self.onDisconnect)
        rtcPeer.onClosedCallbacks.append(self.onClosed)

    def onMessage(self, message: str):
        self.session.updateMotor(self.number, message)

    def onConnect(self):
        self.session.playerConnected(self)

    def onDisconnect(self):
        self.session.playerDisconnected(self)

    def onClosed(self):
        self.session.playerLeft(self)

    def assignNumber(self, number: int):
        self.rtc.send(f"sys.number {number}")
        self.number = number


class EDMOSession:
    def __init__(self, protocol: Bindable[SerialProtocol], numberPlayers: int):
        self.playerNumbers = deque(range(0, numberPlayers))
        self.protocol = protocol
        self.activePlayers = []
        self.waitingPlayers = []

        # These motors represent the canonical state of the edmo robot
        self.motors = [EDMOMotor(i) for i in range(numberPlayers)]
        pass

    # Registered players are not officially active yet
    # A registered player only becomes active when the connection is established
    def registerPlayer(self, rtcPeer: WebRTCPeer):
        player = EDMOPlayer(rtcPeer, self)
        self.waitingPlayers.append(player)
        pass

    # The player finally connected
    # A motor is assigned to the player
    def playerConnected(self, player: EDMOPlayer):
        self.activePlayers.append(player)
        player.assignNumber(self.playerNumbers.popleft())
        self.waitingPlayers.remove(player)
        pass

    # The player has disconnected (due to network faults)
    # A reconnection may happen so we place them into the waiting list
    def playerDisconnected(self, player: EDMOPlayer):
        self.activePlayers.remove(player)
        self.waitingPlayers.append(player)

        if player.number != -1:
            self.playerNumbers.append(player.number)
            player.number = -1

        pass

    # The player connection has been closed
    #  either due to unrecoverable connection failure
    #  or through player intention
    # We remove all references to the player instance
    def playerLeft(self, player: EDMOPlayer):
        if player.number != -1:
            self.playerNumbers.append(player.number)
            player.number = -1

        removeIfExist(self.activePlayers, player)
        removeIfExist(self.waitingPlayers, player)
        pass

    def updateMotor(self, motorNumber: int, command: str):
        self.motors[motorNumber].adjustFrom(command)

    # Update the state of the actual edmo robot
    # All motors are sent through the serial protocol
    async def update(self):
        if not self.protocol.hasValue():
            return

        motor = self.motors[0]

        for motor in self.motors:
            command = motor.asCommand()
            # print(command)
            self.protocol.getNonNullValue().write(command)
