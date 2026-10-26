# from mission_control.config import SETTINGS

from nicegui import ui


@ui.page("/")
def index():
    ui.label("hello world")


def run():
    ui.run(title="My App", reload=False)
