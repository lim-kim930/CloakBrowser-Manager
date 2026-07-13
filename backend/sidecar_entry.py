"""PyInstaller entry point — imports the backend package absolutely."""

import multiprocessing

from backend.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
