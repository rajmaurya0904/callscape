from pkg import Engine
from pkg.core import make


def main():
    e = make()
    e.run([1, 2])
    Engine("a").run([])


if __name__ == "__main__":
    main()
