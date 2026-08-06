"""PyInstaller 打包入口"""

import multiprocessing
import sys


def main():
    from gms.app import App
    app = App()
    app.run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())