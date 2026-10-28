import asyncio
import time
from collections import deque
from dataclasses import replace
from numbers import Number
from typing import Deque, Tuple, Union

from communication_library import ids
from communication_library.communication_manager import CommunicationManager
from communication_library.exceptions import (
    ChecksumMismatchError,
    ClosedTransportError,
    MissingHeaderError,
    TransportTimeoutError,
    UnregisteredCallbackError,
)
from communication_library.frame import Frame
from communication_library.tcp_transport import TcpSettings
from communication_library.transport import TransportType
from mission_control.config import Config


class RocketLink:
    def __init__(self, config: Config, host: str = "127.0.0.1", port: int = 3000):
        self.config = config
        self.cm = CommunicationManager()
        self.cm.change_transport_type(TransportType.TCP)
        self._tcp = TcpSettings(host, port)
        self.latest: dict[str, Union[Number, Tuple[Number, ...]]] = {}
        self.servos: dict[str, Union[Number, Tuple[Number, ...]]] = {}
        self.relays: dict[str, bool] = {}
        self.acks: set[Frame] = set()
        self.altitude_history: Deque[Tuple[float, float]] = deque(maxlen=120)
        self.highest_altitude: float = 0.0
        self.velocity: float = 0.0

        self.connected: bool = False
        self.bad_frames: int = 0

    def connect(self):
        self.cm.connect(self._tcp)
        self.connected = True

    def servo_frame(self, name, position) -> Frame:
        return Frame(
            source=ids.BoardID.SOFTWARE,
            priority=ids.PriorityID.HIGH,
            action=ids.ActionID.SERVICE,
            destination=ids.BoardID.ROCKET,
            device_id=self.config.by_name(name).device_id,
            device_type=ids.DeviceID.SERVO,
            data_type=ids.DataTypeID.INT16,
            operation=ids.OperationID.SERVO.value.POSITION,
            payload=(position,),
        )

    def relay_frame(self, name, on):
        op = (
            ids.OperationID.RELAY.value.OPEN
            if on
            else ids.OperationID.RELAY.value.CLOSE
        )
        return Frame(
            source=ids.BoardID.SOFTWARE,
            priority=ids.PriorityID.HIGH,
            action=ids.ActionID.SERVICE,
            destination=ids.BoardID.ROCKET,
            device_id=self.config.by_name(name).device_id,
            device_type=ids.DeviceID.RELAY,
            data_type=ids.DataTypeID.FLOAT,
            operation=op,
            payload=(0,),  # type: ignore[arg-type]  # Frame pads it to (0.0,)
        )

    async def send_command(self, frame):
        self.cm.push(frame)
        self.cm.send()

    def expected_ack(self, frame: Frame) -> Frame:
        return replace(
            frame,
            source=frame.destination,
            destination=frame.source,
            action=ids.ActionID.ACK,
        )

    def poll(self):
        while self.connected:
            try:
                self.cm.receive()
            except (ChecksumMismatchError, MissingHeaderError):
                self.bad_frames += 1
                continue
            except TransportTimeoutError:
                return
            except ClosedTransportError:
                self.cm.disconnect()
                self.connected = False
            except UnregisteredCallbackError as e:
                self._handle(e.frame)

    def _handle(self, frame: Frame):

        if frame.action == ids.ActionID.ACK:
            self.acks.add(frame)
            if frame.device_type == ids.DeviceID.RELAY:
                name = self.config.by_id("relay", frame.device_id).name
                self.relays[name] = frame.operation == ids.OperationID.RELAY.value.OPEN
        if frame.action != ids.ActionID.FEED:
            return

        if frame.device_type == ids.DeviceID.SENSOR:
            name = self.config.by_id("sensor", frame.device_id).name
            self.latest[name] = frame.data
            if name == "altitude":
                now = time.monotonic()
                altitude = frame.data
                self.highest_altitude = max(self.highest_altitude, altitude)
                if self.altitude_history:
                    last_time, last_alt = self.altitude_history[-1]
                    time_diff = now - last_time
                    self.velocity = (
                        (altitude - last_alt) / (time_diff)
                        if time_diff != 0.0
                        else self.velocity
                    )

                self.altitude_history.append((now, altitude))

        elif frame.device_type == ids.DeviceID.SERVO:
            name = self.config.by_id("servo", frame.device_id).name
            self.servos[name] = frame.data

    async def wait_ack(self, frame: Frame, timeout=1.5):
        timer = time.monotonic()

        expected = self.expected_ack(frame)
        deadline = timer + timeout
        while time.monotonic() < deadline:
            if expected in self.acks:
                self.acks.remove(expected)
                return True
            await asyncio.sleep(0.05)
        return False

    async def run(self):
        while True:
            self.poll()
            await asyncio.sleep(0.01)
