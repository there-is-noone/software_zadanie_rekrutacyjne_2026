import asyncio
import time

from communication_library.frame import Frame
from mission_control.link import RocketLink


class AutoPilot:
    def __init__(self, link):
        self.link: RocketLink = link
        self.stage_name: str = "idle"
        self.logs: list[str] = []
        self.start_time = time.monotonic()

    def log(self, message: str):
        elapsed = time.monotonic() - self.start_time
        self.logs.append(f"{elapsed:6.1f} : {message}")

    async def command(self, frame: Frame, label: str) -> bool:
        self.link.acks.discard(self.link.expected_ack(frame))

        await self.link.send_command(frame)
        success = await self.link.wait_ack(frame)
        self.log(f"{label}: {'ACK' if success else 'no ACK'}")
        return success

    async def servo(self, name: str, is_open: bool) -> bool:
        servo = self.link.config.by_name(name)
        position = servo.open_pos if is_open else servo.closed_pos
        frame = self.link.servo_frame(name, position)
        success = await self.command(frame, f"{name} -> {position}")
        return success

    async def relay(self, name: str, on: bool) -> bool:
        frame = self.link.relay_frame(name, on)
        success = await self.command(frame, f"{name} -> {'ON' if on else 'OFF'}")
        return success

    async def fill(self, propellant: str, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        self.stage_name = f"{propellant} fill"
        intake = f"{propellant}_intake"
        level_sensor = f"{propellant}_level"
        if not await self.servo(intake, True):
            return False
        level = self.link.latest.get(level_sensor, 0)
        while level < 100:
            level = self.link.latest.get(level_sensor, 0)
            if not self.link.connected:
                self.log("link is not connected")
                await self.servo(intake, False)
                return False
            if time.monotonic() > deadline:
                self.log(f"{intake} timed out at {level:.0f} %")
                await self.servo(intake, False)
                return False
            await asyncio.sleep(0.2)
        self.log(f"{propellant} full: {level:.0f} %")
        success = await self.servo(intake, False)
        return success

    async def fill_fuel(self, timeout: float = 30.0) -> bool:
        return await self.fill("fuel", timeout)

    async def fill_oxidizer(self, timeout: float = 30.0) -> bool:
        return await self.fill("oxidizer", timeout)

    async def heater(self, target: int | float = 60, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        self.stage_name = "heater start"
        if not await self.relay("oxidizer_heater", True):
            return False

        pressure = self.link.latest.get("oxidizer_pressure", 0)
        while pressure < target:
            pressure = self.link.latest.get("oxidizer_pressure", 0)
            if not self.link.connected:
                self.log("link is not connected")
                await self.relay("oxidizer_heater", False)
                return False
            if time.monotonic() > deadline:
                self.log(f"{self.stage_name} timed out at {pressure:.1f} bar")
                await self.relay("oxidizer_heater", False)
                return False
            await asyncio.sleep(0.1)
        success = await self.relay("oxidizer_heater", False)
        self.log(f"heater pressure: {pressure:.1f} bar")
        return success

    async def abort_ignition(self):
        await self.relay("igniter", False)
        await self.servo("fuel_main", False)
        await self.servo("oxidizer_main", False)

    async def abort(self):
        self.stage_name = "aborted"
        await self.relay("oxidizer_heater", False)
        await self.abort_ignition()
        await self.servo("fuel_intake", False)
        await self.servo("oxidizer_intake", False)

    async def fire(self) -> bool:
        self.stage_name = "ignition"
        if not self.link.connected:
            self.log("link is not connected")
            return False
        pressure = self.link.latest.get("oxidizer_pressure", 0)
        if not 55 <= pressure <= 65:
            self.log(f"pressure {pressure:.1f} bar outside 55-65, not firing")
            return False
        for intake in ("fuel_intake", "oxidizer_intake"):
            closed = self.link.config.by_name(intake).closed_pos
            position = self.link.servos.get(intake)
            if position != closed:
                self.log(f"{intake} not closed ({position}), not firing")
                return False
        start = time.monotonic()
        if not await self.servo("fuel_main", True):
            await self.abort_ignition()
            return False

        if not await self.servo("oxidizer_main", True):
            await self.abort_ignition()
            return False

        if not await self.relay("igniter", True):
            await self.abort_ignition()
            return False
        timer = time.monotonic()
        await self.relay("igniter", False)
        self.log(f"Completed ignition sequence {(timer - start):.2f} s")
        return True

    async def parachute(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        self.stage_name = "waiting for apogee"

        while True:
            fuel = self.link.latest.get("fuel_level", 100)
            altitude = self.link.latest.get("altitude", 0)
            if fuel <= 0 and altitude > 10 and self.link.velocity <= 0:
                break
            if not self.link.connected:
                self.log("link is not connected")
                return False
            if time.monotonic() > deadline:
                self.log(f"{self.stage_name} timed out at {altitude:.0f} m")
                return False
            await asyncio.sleep(0.1)

        self.log(f"apogee {self.link.highest_altitude:.2f} m")
        self.stage_name = "parachute"
        return await self.relay("parachute", True)

    async def landing(self, timeout: float = 300.0, silence: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        self.stage_name = "descent"

        while True:
            history = self.link.altitude_history
            last_reading = history[-1][0] if history else time.monotonic()
            quiet = time.monotonic() - last_reading
            altitude = self.link.latest.get("altitude", 0)
            if altitude <= 1:
                self.log("landed")
                break
            if altitude < 10 and quiet > silence:
                self.log(f"landed (feed stopped at {altitude:.1f} m)")
                break
            if not self.link.connected:
                self.log("link is not connected")
                return False
            if time.monotonic() > deadline:
                self.log(f"{self.stage_name} timed out at {altitude:.0f} m")
                return False
            await asyncio.sleep(0.2)
        self.stage_name = "landed"
        return True

    async def mission(self) -> bool:
        if not await self.fill_oxidizer():
            self.log("Failed while filling the oxidizer")
            return False
        if not await self.fill_fuel():
            self.log("Failed while filling the fuel")
            return False
        if not await self.heater():
            self.log("Failed while pressurizing")
            return False
        if not await self.fire():
            self.log("Failed while firing")
            return False
        if not await self.parachute():
            self.log("Failed while parachuting")
            return False
        if not await self.landing():
            self.log("Failed while landing")
            return False
        return True
