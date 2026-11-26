from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--piper-render":
        from .piper_worker import main as piper_worker_main

        raise SystemExit(piper_worker_main(sys.argv[2:]))

    import tkinter as tk

    from .controller import AppController

    root = tk.Tk()
    AppController(root)
    root.mainloop()


if __name__ == "__main__":
    main()
