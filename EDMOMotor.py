import struct

from Server.EDMOCommands import EDMOCommands, EDMOPacket


class EDMOMotor:
    def __init__(self, id: int) -> None:
        self._amp: float = 0
        self._offset: float = 90
        self._freq: float = 0
        self._phaseShift: float = 0
        self._id = id
        pass

    def adjustFrom(self, input: str):
        """Takes an input str, and adjusts the parameters of the associated motor"""
        splits = input.split(" ")
        command = splits[0].lower()
        value = float(splits[1])

        match (command):
            case "amp":
                self._amp = value
            case "off":
                self._offset = value
            case "freq":
                self._freq = value
            case "phb":
                self._phaseShift = value
            case _:
                pass

    @property
    def motorNumber(self):
        return self._id

    def __str__(self):
        return f"EDMOMotor(id={self._id}, frequency={self._freq},  amplitude={self._amp}, offset={self._offset}, phaseShift={self._phaseShift})"

    def asCommand(self):
        command = struct.pack(
            "<Bffff",
            self._id,
            self._freq,
            self._amp,
            self._offset,
            self._phaseShift,
        )

        return EDMOPacket.create(EDMOCommands.UPDATE_OSCILLATOR, command)
