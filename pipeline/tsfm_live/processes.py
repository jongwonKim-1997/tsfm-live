"""Keep background Windows child processes from opening console windows."""
import os
import subprocess


def background_process_options():
    # pythonw hides only its own console; each console child needs this flag.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
