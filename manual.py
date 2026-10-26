import time

from communication_library import ids
from communication_library.communication_manager import (
    CommunicationManager,
    TransportType,
)
from communication_library.exceptions import (
    TransportTimeoutError,
    UnregisteredCallbackError,
)
from communication_library.frame import Frame
from communication_library.tcp_transport import TcpSettings

SERVO = {"fuel_intake": 0, "oxidizer_intake": 1, "fuel_main": 2, "oxidizer_main": 3}
RELAY = {"oxidizer_heater": 0, "igniter": 1, "parachute": 2}
SENSOR = {0: "fuel", 1: "oxidizer", 2: "altitude", 3: "pressure", 4: "angle"}


def on_altitude(frame: Frame):
    print(f"Registered frame received: {frame}")


latest = {}  # last value of every sensor, filled by read()

cm = CommunicationManager()
cm.change_transport_type(TransportType.TCP)
cm.connect(TcpSettings("127.0.0.1", 3000))


def servo_frame(name, position) -> Frame:
    return Frame(
        source=ids.BoardID.SOFTWARE,
        priority=ids.PriorityID.HIGH,
        action=ids.ActionID.SERVICE,
        destination=ids.BoardID.ROCKET,
        device_id=SERVO[name],
        device_type=ids.DeviceID.SERVO,
        data_type=ids.DataTypeID.INT16,
        operation=ids.OperationID.SERVO.value.POSITION,
        payload=(position,),
    )
    cm.register_callback(on_altitude, altitude_frame)
    cm.connect(TcpSettings("127.0.0.1", 3000))


def relay_frame(name, on):
    op = ids.OperationID.RELAY.value.OPEN if on else ids.OperationID.RELAY.value.CLOSE
    return Frame(
        source=ids.BoardID.SOFTWARE,
        priority=ids.PriorityID.HIGH,
        action=ids.ActionID.SERVICE,
        destination=ids.BoardID.ROCKET,
        device_id=RELAY[name],
        device_type=ids.DeviceID.RELAY,
        data_type=ids.DataTypeID.FLOAT,
        operation=op,
        payload=(0,),  # type: ignore[arg-type]  # Frame pads it to (0.0,)
    )


def send(*frames):
    for f in frames:
        cm.push(f)
    while cm.send() is not None:
        pass
    read(0.5)


def read(seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        try:
            cm.receive()
        except TransportTimeoutError:
            time.sleep(0.01)
        except UnregisteredCallbackError as e:
            frame = e.frame
            if frame.action == ids.ActionID.ACK:
                print("ACK", frame)
            else:
                latest[SENSOR[frame.device_id]] = round(frame.data, 1)


def status():
    read(1.2)  # at least one feed cycle
    print(latest)


def open_valve(name):
    send(servo_frame(name, 0))


def close_valve(name):
    send(servo_frame(name, 100))


def heater(on):
    send(relay_frame("oxidizer_heater", on))


def parachute():
    send(relay_frame("parachute", True))


def fire():
    # all three back to back: well inside the 1 s window
    send(
        servo_frame("fuel_main", 0),
        servo_frame("oxidizer_main", 0),
        relay_frame("igniter", True),
    )


if __name__ == "__main__":
    cm = CommunicationManager()
    cm.change_transport_type(TransportType.TCP)
    cm.connect(TcpSettings("127.0.0.1", 3000))
    print(
        "Connected. Commands: open_valve(name), close_valve(name), heater(on), "
        "fire(), parachute(), status()"
    )
