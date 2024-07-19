import struct

(AMPLITUDE, OFFSET, PHASESHIFT, FREQUENCY, SERVOMIN, SERVOMAX, PRINT) = map(
    int, [0, 1, 2, 3, 4, 5, 4294967295]
)


class EDMOMotor:
    def __init__(self, id: int) -> None:
        self._amp: float = 0
        self._offset: float = 90
        self._freq: float = 0
        self._phaseShift: float = 0
        self._id = id
        pass

    def adjustFrom(self, input: str):
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
            "@Iffff",
            self._id,
            self._freq,
            self._amp,
            self._offset,
            self._phaseShift,
        )

        commandBA = bytearray(b"\x01" + command)
        commandBA = commandBA.replace(b"ED", b"E\\D")
        commandBA = commandBA.replace(b"MO", b"M\\O")
        escapedCommand = bytes(commandBA)

        full = b"E" + b"D" + escapedCommand + b"M" + b"O"
        # print(full)

        return full
