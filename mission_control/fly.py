import asyncio
import sys
import time

from mission_control.autopilot import AutoPilot
from mission_control.config import Config
from mission_control.link import RocketLink


def print_new_logs(pilot: AutoPilot, printed: int) -> int:
    for line in pilot.logs[printed:]:
        print(line, flush=True)
    return len(pilot.logs)


def print_status(link: RocketLink, pilot: AutoPilot):
    print(
        f"   [{pilot.stage_name}] alt={link.sensor('altitude'):6.1f} m "
        f"v={link.velocity:6.1f} m/s fuel={link.sensor('fuel_level'):5.1f} % "
        f"ox={link.sensor('oxidizer_level'):5.1f} % "
        f"p={link.sensor('oxidizer_pressure'):5.1f} bar",
        flush=True,
    )


async def fly(link: RocketLink, pilot: AutoPilot):
    mission = asyncio.create_task(pilot.mission())
    printed = 0
    next_status = time.monotonic()
    try:
        while not mission.done():
            printed = print_new_logs(pilot, printed)
            if time.monotonic() >= next_status:
                print_status(link, pilot)
                next_status += 5
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        print("interrupted, making the rocket safe...", flush=True)
        mission.cancel()
        await asyncio.wait([mission])
        await pilot.abort()
        print_new_logs(pilot, printed)
        raise
    print_new_logs(pilot, printed)
    return mission.result()

    result = await pilot.mission()


async def main() -> bool:
    link = RocketLink(Config())
    try:
        link.connect()
    except OSError:
        print("can't reach the proxy, is tcp_proxy.py running?")
        return False

    link_task = asyncio.create_task(link.run())
    try:
        await asyncio.sleep(1.5)
        pilot = AutoPilot(link)
        result = await fly(link, pilot)
    finally:
        link_task.cancel()

    print(f"mission {'succeeded' if result else 'failed'} (stage: {pilot.stage_name})")
    return result


if __name__ == "__main__":
    try:
        ok = asyncio.run(main())
    except KeyboardInterrupt:
        ok = False
    sys.exit(0 if ok else 1)
