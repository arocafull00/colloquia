import multiprocessing
import os
import sys

from config import APP, CONFIG_DIR, LOG_PATH, WIN

if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def already_running():
    if WIN:
        import ctypes

        already_running.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ColloquiaSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.user32.MessageBoxW(None, f"{APP} ya está abierto.", APP, 0x40)
            return True
        return False
    import fcntl

    already_running.lock = open(os.path.join(CONFIG_DIR, "colloquia.lock"), "w")
    try:
        fcntl.flock(already_running.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        print(f"{APP} ya está abierto.")
        return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if args:
        import pipeline

        sys.exit(pipeline.main(args))
    if already_running():
        return
    from ui import App

    App().mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
