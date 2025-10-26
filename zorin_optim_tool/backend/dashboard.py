import psutil
import platform
import time
import shutil


def get_system_info():
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    uname = platform.uname()
    os_str = f"{uname.system} {platform.release()}"
    kernel = uname.release
    uptime = time.time() - psutil.boot_time()
    uptime_h = int(uptime // 3600)
    return {
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disk_percent": disk,
        "os": os_str,
        "kernel": kernel,
        "uptime": f"{uptime_h}h",
    }
