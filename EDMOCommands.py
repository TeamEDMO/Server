from attr import dataclass


class EDMOCommands:
    (
        IDENTIFY,
        SESSION_START,
        GET_TIME,
        UPDATE_OSCILLATOR,
        SEND_MOTOR_DATA,
        SEND_IMU_DATA,
    ) = range(6)

    INVALID = -1

    @classmethod
    def sanitize(cls, instruction: int):
        if instruction not in range(6):
            return cls.INVALID

        return instruction


@dataclass
class EDMOCommand:
    Instruction: int
    Data: bytes


class EDMOPacket:
    HEADER = b"ED"
    FOOTER = b"MO"

    @classmethod
    def create(cls, *args: bytes | int) -> bytes:
        output = bytearray()
        output.extend(cls.HEADER)

        data = bytearray()
        for arg in args:
            if isinstance(arg, int):
                data.append(arg)
            elif isinstance(arg, bytes):
                data.extend(arg)

        data = cls.escape(data)

        output.extend(data)
        output.extend(cls.FOOTER)

        return bytes(output)

    @classmethod
    def fromCommand(cls, command: EDMOCommand):
        return cls.create(command.Instruction, command.Data)

    @classmethod
    def tryParse(cls, packet: bytes):
        if not packet.startswith(cls.HEADER) or not packet.endswith(cls.FOOTER):
            return EDMOCommand(EDMOCommands.INVALID, None)  # type:ignore

        command = packet[2:-2]

        instruction = EDMOCommands.sanitize(command[0])
        data = cls.unescape(command[1:])

        return EDMOCommand(instruction, data)

    @classmethod
    def escape(cls, data: bytearray):
        return (
            data.replace(b"\\", b"\\\\")
            .replace(cls.HEADER, b"E\\D")
            .replace(cls.FOOTER, b"M\\O")
        )

    @classmethod
    def unescape(cls, data: bytes):
        unescaped = bytearray()

        i = 0
        while i < len(data):
            if data[i] == int.from_bytes(b"\\"):
                i += 1
                if i >= len(data):
                    break

            unescaped.append(data[i])
            i += 1

        return unescaped
