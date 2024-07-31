# Holds 1 session to be used with 1 robot

from collections import deque
from itertools import count
import json
from random import Random, randint
import struct
from typing import TYPE_CHECKING, Callable, Self

from EDMOCommands import EDMOCommand, EDMOCommands, EDMOPacket
from EDMOMotor import EDMOMotor
from FusedCommunication import FusedCommunicationProtocol

from Logger import SessionLogger
from Utilities.Helpers import removeIfExist
from WebRTCPeer import WebRTCPeer

if TYPE_CHECKING:
    from EDMOSession import EDMOSession


class EDMOPlayer:
    SAMPLE_NAMES = [
        "John",
        "Stacy",
        "Oistin",
        "Alice",
        "Bob",
        "Charlie",
        "Nat",
        "Kieren",
        "Eve",
        "Frank",
    ]

    def __init__(self, rtcPeer: WebRTCPeer, edmoSession: "EDMOSession"):
        self.rtc = rtcPeer
        self.session = edmoSession
        randomNumber = randint(0, len(self.SAMPLE_NAMES) - 1)

        self.number = -1

        self.voted = randomNumber % 2 == 0

        self.name = self.SAMPLE_NAMES[randomNumber]

        rtcPeer.onMessage.append(self.onMessage)
        rtcPeer.onConnectCallbacks.append(self.onConnect)
        rtcPeer.onDisconnectCallbacks.append(self.onDisconnect)
        rtcPeer.onClosedCallbacks.append(self.onClosed)

    def onMessage(self, message: str):
        self.session.updateMotor(self.number, message)
        self.session.sessionLog.write(f"Input_Player{self.number}", message=message)

    def sendMessage(self, message: str):
        self.rtc.send(message)

    def onConnect(self):
        self.session.playerConnected(self)

    def onDisconnect(self):
        self.session.playerDisconnected(self)

    def onClosed(self):
        self.session.playerLeft(self)

    def assignNumber(self, number: int):
        self.rtc.send(f"sys.number {number}")
        self.number = number


# flake8: noqa: F811
class EDMOSession:
    TASK_LIST: list[str] | None = None

    @classmethod
    def loadTasks(cls) -> dict[str, bool]:
        if not cls.TASK_LIST:
            with open("tasks.json") as f:
                cls.TASK_LIST = json.load(f)

        if not cls.TASK_LIST:
            return {}

        result: dict[str, bool] = {}

        for task in cls.TASK_LIST:
            result[task] = False

        return result

    def __init__(
        self,
        protocol: FusedCommunicationProtocol,
        numberPlayers: int,
        sessionRemoval: Callable[[Self], None],
    ):
        self.sessionLog = SessionLogger(protocol.identifier)
        self.removeSelf = sessionRemoval

        self.playerNumbers = deque(range(0, numberPlayers))
        self.protocol = protocol
        protocol.onMessageReceived = self.messageReceived

        self.activePlayers: list[EDMOPlayer] = []
        self.waitingPlayers: list[EDMOPlayer] = []

        self.offsetTime = 0

        self.tasks = self.loadTasks()

        self.helpEnabled = False

        protocol.onConnectionEstablished = self.onEDMOReconnect
        self.onEDMOReconnect()

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

        self.sessionLog.write("Session", f"Player {player.number} connected.")
        pass

    # The player has disconnected (due to network faults)
    # A reconnection may happen so we place them into the waiting list
    def playerDisconnected(self, player: EDMOPlayer):
        self.sessionLog.write("Session", f"Player {player.number} disconnected.")

        self.activePlayers.remove(player)
        self.waitingPlayers.append(player)

        if player.number != -1:
            self.playerNumbers.append(player.number)
            player.number = -1

    # The player connection has been closed
    #  either due to unrecoverable connection failure
    #  or through player intention
    # We remove all references to the player instance
    def playerLeft(self, player: EDMOPlayer):
        self.sessionLog.write("Session", f"Player {player.number} left.")

        if player.number != -1:
            self.playerNumbers.append(player.number)
            player.number = -1

        removeIfExist(self.activePlayers, player)
        removeIfExist(self.waitingPlayers, player)

        if not self.hasPlayers():
            self.protocol.onConnectionEstablished = None
            self.removeSelf(self)

        pass

    def onEDMOReconnect(self):
        self.protocol.write(
            EDMOPacket.create(
                EDMOCommands.SESSION_START, struct.pack("<L", self.offsetTime)
            )
        )

    def updateMotor(self, motorNumber: int, command: str):
        self.motors[motorNumber].adjustFrom(command)

    def hasPlayers(self):
        return len(self.activePlayers) > 0 or len(self.waitingPlayers) > 0

    def messageReceived(self, command: EDMOCommand):
        # Ignore malformed message
        if command.Instruction == EDMOCommands.INVALID:
            return

        if command.Instruction == EDMOCommands.GET_TIME:
            self.offsetTime = struct.unpack("<L", command.Data)[0]
        elif command.Instruction == EDMOCommands.SEND_MOTOR_DATA:
            self.parseMotorPacket(command.Data)
            # log motor data
            pass
        elif command.Instruction == EDMOCommands.SEND_IMU_DATA:
            self.parseIMUPacket(command.Data)
            # log IMU data
            pass
        pass

    def sendFeedback(self, message: str):
        for p in self.activePlayers:
            p.sendMessage(f"[FEEDBACK] {message}")

        print(f"feedback {message} is sent to group {self.protocol.identifier}")
        self.sessionLog.write("Session", f"Teacher sent feedback: {message}")

    # Update the state of the actual edmo robot
    # All motors are sent through the serial protocol
    async def update(self):
        if not self.protocol.hasConnection():
            return

        motor = self.motors[0]

        for motor in self.motors:
            command = motor.asCommand()
            # print(command)
            self.protocol.write(command)

        self.protocol.write(EDMOPacket.create(EDMOCommands.SEND_MOTOR_DATA))
        self.protocol.write(EDMOPacket.create(EDMOCommands.SEND_IMU_DATA))
        self.protocol.write(EDMOPacket.create(EDMOCommands.GET_TIME))
        await self.sessionLog.update()

    async def close(self):
        await self.sessionLog.flush()

        for p in self.activePlayers:
            await p.rtc.close()

        for p in self.waitingPlayers:
            await p.rtc.close()


    def parseMotorPacket(self, data:bytes):
        parsedContent = struct.unpack("<Bfffff", data)

        stringified = f"Frequency: {parsedContent[1]}, Amplitude: {parsedContent[2]}, Offset: {parsedContent[3]}, Phase Shift: {parsedContent[4]}, Phase: {parsedContent[5]}"

        self.sessionLog.write(f"Motor{parsedContent[0]}", stringified)


    def parseIMUPacket(self, data: bytes):

        parsedContent = struct.unpack("<LB3xfffLB3xfffLB3xfffLB3xfffLB3xffff", data)

        accelaration = f"Acceleration: {{Time: {parsedContent[0]}, Status: {parsedContent[1]}, Value: ({parsedContent[2]},{parsedContent[3]},{parsedContent[4]})}}"
        gyroscope = f"Gyroscope: {{Time: {parsedContent[5]}, Status: {parsedContent[6]}, Value: ({parsedContent[7]},{parsedContent[8]},{parsedContent[9]})}}"
        magnetic = f"Magnetic: {{Time: {parsedContent[10]}, Status: {parsedContent[11]}, Value: ({parsedContent[12]},{parsedContent[13]},{parsedContent[14]})}}"
        gravity = f"Gravity: {{Time: {parsedContent[15]}, Status: {parsedContent[16]}, Value: ({parsedContent[17]},{parsedContent[18]},{parsedContent[19]})}}"
        rotation = f"Rotation: {{Time: {parsedContent[20]}, Status: {parsedContent[21]}, Value: ({parsedContent[22]},{parsedContent[23]},{parsedContent[24]}, {parsedContent[25]})}}"

        final = f"{{{accelaration},{gyroscope},{magnetic},{gravity}, {rotation}}}"

        self.sessionLog.write("IMU", final)
        pass

    def getSessionInfo(self):
        object = {}

        robotID = self.protocol.identifier

        players = [p.name for p in self.activePlayers]

        object["robotID"] = robotID
        object["names"] = players
        object["HelpNumber"] = len([p for p in self.activePlayers if p.voted])

        return object

    def getDetailedInfo(self):
        object = {}
        players = []

        for p in self.activePlayers:
            player = {}
            player["name"] = p.name
            player["HelpRequested"] = p.voted

            players.append(player)

        object["robotID"] = self.protocol.identifier
        object["players"] = players

        tasks = []

        for t in self.tasks:
            task = {}
            task["Title"] = t
            task["Value"] = self.tasks[t]

            tasks.append(task)

        object["tasks"] = tasks
        object["helpEnabled"] = self.helpEnabled

        return object
    

    def setTasks(self, task: str, value: bool):
        if task not in self.tasks:
            return False

        self.tasks[task] = value

        # TODO: NOTIFY PLAYERS

        return True

    def setHelpEnabled(self, value):
        if self.helpEnabled == value:
            return

        self.helpEnabled = value
        if not value:
            for p in self.activePlayers:
                p.voted = False

        for p in self.activePlayers:
            p.sendMessage(f"HelpEnabled {"1" if value else "0"}")

    def setSimpleView(self, value):
        for p in self.activePlayers:
            p.sendMessage(f"SimpleMode {"1" if value else "0"}")
