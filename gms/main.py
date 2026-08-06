"""入口：python -m gms"""

import sys


def main():
    from .app import App
    app = App()
    app.run()


if __name__ == "__main__":
    sys.exit(main())