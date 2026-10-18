import os
from . import helpers
from .helpers import slugify as slug


class Base:
    def start(self):
        self.setup()

    def setup(self):
        pass


class Engine(Base):
    """Runs jobs."""

    def __init__(self, name):
        self.name = slug(name)

    def run(self, jobs):
        self.start()
        for j in jobs:
            self.step(j)
        helpers.log(os.getcwd())

    def step(self, job):
        return helpers.fmt(job)


def make() -> Engine:
    return Engine("x")
