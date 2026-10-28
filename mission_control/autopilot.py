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

    async def fill_oxidizer(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        self.stage_name = "oxidizer fill"
        if not await self.servo("oxidizer_intake", True):
            return False
        while self.link.latest.get("oxidizer_level", 0) < 100:
            level = self.link.latest.get("oxidizer_level", 0)
            if not self.link.connected:
                self.log("link is not connected")
                return False
            if time.monotonic() > deadline:
                self.log(f"oxidizer fill timed out at {level:.0f} %")
                return False
            await asyncio.sleep(0.2)
        pressure = self.link.latest.get("oxidizer_pressure", 0)
        self.log(f"oxidizer full: {level:.0f} %, {pressure:.1f} bar")
        success = await self.servo("oxidizer_intake", False)
        return success
