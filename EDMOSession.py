# Holds 1 session to be used with 1 robot

import asyncio
from heapq import heapify
import heapq
import itertools
import json
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
    def __init__(self, rtcPeer: WebRTCPeer, name: str,  edmoSession: "EDMOSession"):
        self.rtc = rtcPeer
        self.session = edmoSession

        self.number = -1

        self.voted =  False

        self.name = name

        rtcPeer.onMessage.append(self.onMessage)
        rtcPeer.onConnectCallbacks.append(self.onConnect)
        rtcPeer.onDisconnectCallbacks.append(self.onDisconnect)

    def onMessage(self, message: str):
        self.session.sessionLog.write(f"Input_Player{self.number}", message=message)
        parts = message.split(" ")
        if(parts[0] == "vote"):
            self.voted = (int(parts[1]) == 1)
            self.session.broadcastPlayerList()
            return
    
        if(parts[0] == "freq"):
            self.session.setFreq(float(parts[1]))
            return
        
        if(parts[0] == "phb"):
            self.session.setPhb(self.number, float(parts[1]))

        self.session.updateMotor(self.number, message)
                
        for c in [c for c in  self.session.activeOverriders if c.number == self.number and c != self]:
            self.session.sendMotorParams(c)

    def sendMessage(self, message: str):
        try:
            self.rtc.send(message)
        except (Exception):
            asyncio.create_task(self.rtc.close())
    

    def onConnect(self):
        self.session.playerConnected(self)

    def onDisconnect(self):
        self.session.playerDisconnected(self)

    def assignNumber(self, number: int):
        self.rtc.send(f"sys.number {number}")
        self.number = number
        self.sendMessage(f"ID {self.number}")

    def dict(self):
        dict = {}

        dict["number"] = self.number
        dict["name"] = self.name
        dict["voted"] = self.voted

        return dict

    def json(self):
        return json.dumps(self.dict())
    
class EDMOOveridePlayer(EDMOPlayer):
    def __init__(self, rtcPeer: WebRTCPeer, id: int,  edmoSession: "EDMOSession"):
        super().__init__( rtcPeer, "Overrider" , edmoSession)
        self.assignNumber(id)

    def onMessage(self, message: str):
        self.session.sessionLog.write(f"Input_Override{self.number}", message=message)
        parts = message.split(" ")
        if(parts[0] == "vote"):
            self.voted = (int(parts[1]) == 1)
            self.session.broadcastPlayerList()
            return
    
        if(parts[0] == "freq"):
            self.session.setFreq(float(parts[1]))
            return
        
        if(parts[0] == "phb"):
            self.session.setPhb(self.number, float(parts[1]))

        self.session.updateMotor(self.number, message)

        combined = itertools.chain(self.session.activePlayers, self.session.activeOverriders)
        for c in [c for c in combined if c.number == self.number and c != self]:
            self.session.sendMotorParams(c)

    def onConnect(self):
        self.session.overriderConnected(self)
        self.sendMessage(f"ID {self.number}")

    def onDisconnect(self):
        self.session.playerDisconnected(self)


class TaskEntry:
    def __init__(self, strings: dict[str, str], completed: bool = False):
        self.strings = strings
        self.completed = completed

# flake8: noqa: F811
class EDMOSession:
    TASK_LIST: list[dict[str, str]] | None = None
    MAX_PLAYER_COUNT = 4

    # A one time method to load task info from a file
    @classmethod
    def loadTasks(cls) -> dict[str, TaskEntry]:
        if not cls.TASK_LIST:
            with open("tasks.json") as f:
                cls.TASK_LIST = json.load(f)

        if not cls.TASK_LIST:
            return {}

        result: dict[str, TaskEntry] = {}

        for task in cls.TASK_LIST:
            keys = list(task.keys())
            if(len(keys) == 0):
                continue

            firstLocaleEntry :str = task[keys[0]]
            taskKey = "".join([e for e in firstLocaleEntry if e.isalnum()])
            
            result[taskKey] = TaskEntry(task)

        return result

    def __init__(
        self,
        protocol: FusedCommunicationProtocol,
        numberPlayers: int,
        sessionRemoval: Callable[[Self], None],
    ):
        self.sessionLog = SessionLogger(protocol.identifier)
        self.removeSelf = sessionRemoval

        self.usedNumbers = 0

        self.playerNumbers = list(range(0, self.MAX_PLAYER_COUNT))
        heapify(self.playerNumbers)
        self.protocol = protocol
        protocol.onMessageReceived = self.messageReceived

        self.activePlayers: list[EDMOPlayer] = []
        self.activeOverriders : list[EDMOPlayer] = []
        self.waitingPlayers: list[EDMOPlayer] = []

        self.offsetTime = 0

        self.tasks = self.loadTasks()

        self.helpEnabled = False
        self.simpleMode = True

        protocol.onConnectionEstablished = self.onEDMOReconnect
        self.onEDMOReconnect()

        # These motors represent the canonical state of the edmo robot
        self.motors = [EDMOMotor(i) for i in range(numberPlayers)]
        pass

    # Registered players are not officially active yet
    # A registered player only becomes active when the connection is established
    def registerPlayer(self, rtcPeer: WebRTCPeer, username: str):
        if(len(self.playerNumbers) == 0):
            return False
        player = EDMOPlayer(rtcPeer, username, self)
        self.waitingPlayers.append(player)

        return True

    def registerOverrider(self, rtcPeer : WebRTCPeer, overrideID: int):
        overrider = EDMOOveridePlayer(rtcPeer, overrideID, self)

        self.activeOverriders.append(overrider)

        return True


    # The player finally connected
    # A motor is assigned to the player
    def playerConnected(self, player: EDMOPlayer):
        player.assignNumber(heapq.heappop(self.playerNumbers))
        self.waitingPlayers.remove(player)
        self.activePlayers.append(player)
        self.sessionLog.write("Session", message=f"Player {player.number} connected. ({player.name})")

        self.broadcastPlayerList()
        player.sendMessage(f"TaskInfo {json.dumps(self.getTasks())}")
        self.sendMotorParams(player)
        player.sendMessage(f"HelpEnabled {"1" if self.helpEnabled else "0"}")
        player.sendMessage(f"SimpleMode {"1" if self.simpleMode else "0"}")
        
        pass

    def overriderConnected(self, overrider : EDMOOveridePlayer):
        self.sessionLog.write("Session", message=f"Overrider for {overrider.number} connected.")

        self.broadcastPlayerList()
        overrider.sendMessage(f"TaskInfo {json.dumps(self.getTasks())}")
        self.sendMotorParams(overrider)
        overrider.sendMessage(f"HelpEnabled {"1" if self.helpEnabled else "0"}")
        overrider.sendMessage(f"SimpleMode {"1" if self.simpleMode else "0"}")


    # The player has disconnected (due to network faults)
    # A reconnection may happen so we place them into the waiting list
    def playerDisconnected(self, player: EDMOPlayer):
        self.sessionLog.write("Session", f"Player {player.number} disconnected. ({player.name})")

        self.activePlayers.remove(player)

        self.broadcastPlayerList()

        if player.number != -1:
            heapq.heappush(self.playerNumbers, player.number)
            self.playerNumbers
            player.number = -1

        removeIfExist(self.activePlayers, player)
        removeIfExist(self.waitingPlayers, player)

        if not self.hasPlayers():
            self.protocol.onConnectionEstablished = None
            self.removeSelf(self)

        pass

    # The player has disconnected (due to network faults)
    # A reconnection may happen so we place them into the waiting list
    def overriderDisconnected(self, overrider: EDMOPlayer):
        self.sessionLog.write("Session", f"Overrider for {overrider.number} disconnected.")

        removeIfExist(self.activeOverriders, overrider)

    # If the edmo associated with this session is reconnected
    # We realign the edmo timestamp back with the session timestamp
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


    # Notify all players about changes in the task list
    def broadcastTaskList(self):
        jsonDump = json.dumps(self.getTasks())

        for player in self.activePlayers:
            player.sendMessage(f"TaskInfo {jsonDump}")

    # Notify all players about changes in the player list
    def broadcastPlayerList(self):
        playerList = [s.dict() for s in self.activePlayers]

        jsonDump = json.dumps(playerList)

        for player in self.activePlayers:
            player.sendMessage(f"PlayerInfo {jsonDump}")

    # Notify all players that help button is enabled
    def broadcastHelpEnabled(self):
        for p in self.activePlayers:
            p.sendMessage(f"HelpEnabled {"1" if self.helpEnabled else "0"}")

    # Sends the current parameter of a motor associated with a player
    def sendMotorParams(self, recipient: EDMOPlayer):
        motor = self.motors[recipient.number]
        recipient.sendMessage(f"amp {motor._amp}")
        recipient.sendMessage(f"freq {motor._freq}")
        recipient.sendMessage(f"off {motor._offset}")

        for motor in self.motors:
            recipient.sendMessage(f"phb {motor._id} {motor._phaseShift}")

    def setFreq(self,newValue:float):
        for motor in self.motors:
            motor._freq = newValue

        for player in self.activePlayers:
            player.sendMessage(f"freq {newValue}")

    def setPhb(self, id : int, newValue:float):
        for player in self.activePlayers:
            if(player.number == id):
                continue
            player.sendMessage(f"phb {id} {newValue}")


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

#region EDMO COMMUNICATION 
# Functions to handle packets delivered by the EDMO itself

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


    def parseMotorPacket(self, data:bytes):
        """We've received the motor state from the edmo, we log it."""

        parsedContent = struct.unpack("<Bfffff", data)

        stringified = f"Frequency: {parsedContent[1]}, Amplitude: {parsedContent[2]}, Offset: {parsedContent[3]}, Phase Shift: {parsedContent[4]}, Phase: {parsedContent[5]}"

        self.sessionLog.write(f"Motor{parsedContent[0]}", stringified)


    def parseIMUPacket(self, data: bytes):
        """We've received the IMU state from the edmo, we log it."""

        parsedContent = struct.unpack("<LB3xfffLB3xfffLB3xfffLB3xfffLB3xffff", data)

        accelaration = f"Acceleration: {{Time: {parsedContent[0]}, Status: {parsedContent[1]}, Value: ({parsedContent[2]},{parsedContent[3]},{parsedContent[4]})}}"
        gyroscope = f"Gyroscope: {{Time: {parsedContent[5]}, Status: {parsedContent[6]}, Value: ({parsedContent[7]},{parsedContent[8]},{parsedContent[9]})}}"
        magnetic = f"Magnetic: {{Time: {parsedContent[10]}, Status: {parsedContent[11]}, Value: ({parsedContent[12]},{parsedContent[13]},{parsedContent[14]})}}"
        gravity = f"Gravity: {{Time: {parsedContent[15]}, Status: {parsedContent[16]}, Value: ({parsedContent[17]},{parsedContent[18]},{parsedContent[19]})}}"
        rotation = f"Rotation: {{Time: {parsedContent[20]}, Status: {parsedContent[21]}, Value: ({parsedContent[22]},{parsedContent[23]},{parsedContent[24]}, {parsedContent[25]})}}"

        final = f"{{{accelaration},{gyroscope},{magnetic},{gravity}, {rotation}}}"

        self.sessionLog.write("IMU", final)
        pass
#endregion

#region API ENDPOINT HANDLERS
# Functions in this region are meant to be used by the backed to respond to Rest API calls

    def getSessionInfo(self):
        object = {}

        robotID = self.protocol.identifier

        players = [p.name for p in self.activePlayers]

        object["robotID"] = robotID
        object["names"] = players
        object["HelpNumber"] = len([p for p in self.activePlayers if p.voted])

        return object
    
    def getTasks(self):
        tasks = []

        for t in self.tasks:
            task = {}
            task["key"] = t
            task["strings"] = self.tasks[t].strings
            task["completed"] = self.tasks[t].completed

            tasks.append(task)

        return tasks


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

        tasks = self.getTasks()

        object["tasks"] = tasks
        object["helpEnabled"] = self.helpEnabled

        return object
    

    def setTasks(self, taskKey: str, value: bool):
        if taskKey not in self.tasks:
            return False

        self.tasks[taskKey].completed = value

        self.broadcastTaskList()

        return True

    def setHelpEnabled(self, value):
        if self.helpEnabled == value:
            return

        self.helpEnabled = value
        if not value:
            for p in self.activePlayers:
                p.voted = False

        self.broadcastHelpEnabled()

    # A teacher has sent feedback/guide to this session, broadcast to all player
    def sendFeedback(self, message: str):
        for p in self.activePlayers:
            p.sendMessage(f"Feedback {message}")

        print(f"feedback {message} is sent to group {self.protocol.identifier}")
        self.sessionLog.write("Session", f"Teacher sent feedback: {message}")


    def setSimpleView(self, value):
        self.simpleMode = value
        for p in self.activePlayers:
            p.sendMessage(f"SimpleMode {"1" if value else "0"}")

#endregion
