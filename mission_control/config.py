from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "simulator_config.yaml"


@dataclass(frozen=True)
class Device:
    kind: str
    name: str
    board: str
    device_id: int
    open_pos: int | None = None
    closed_pos: int | None = None
    data_type: str | None = None


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        with open(path) as f:
            raw = yaml.safe_load(f)
        self.devices: list[Device] = []
        for kind, group in raw["devices"].items():
            for name, s in group.items():
                self.devices.append(
                    Device(
                        kind=kind,
                        name=name,
                        board=s["board"],
                        device_id=s["device_id"],
                        open_pos=s.get("open_pos"),
                        closed_pos=s.get("closed_pos"),
                        data_type=s.get("data_type"),
                    )
                )

        self._by_name = {d.name: d for d in self.devices}
        self._by_id = {(d.kind, d.device_id): d for d in self.devices}

    def by_name(self, name: str) -> Device:
        return self._by_name[name]

    def by_id(self, kind: str, device_id: int) -> Device:
        return self._by_id[(kind, device_id)]
