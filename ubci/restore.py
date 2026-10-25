"""A recovery job that only flashes the lab's image back onto one
device, for a test job that ended before its own restore.

python3 -m ubci.restore <board> <device> <restore url> <token name> [<header>]"""
import sys

from fwci import lava_jobs as lj

from . import config, jobs


def render(board_name, device, restore):
    b = config.board(board_name)
    job = lj.job(b["lava"]["device_type"], "u-boot-ci restore lab image %s %s" % (board_name, device),
                 jobs.restore_actions(b, restore), {"project": "u-boot-ci", "board": board_name,
                                                    "restore-for": device},
                 priority="medium", job_minutes=60)
    job["device"] = device
    return job


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        raise SystemExit(__doc__)
    board, device, url, token = sys.argv[1:5]
    restore = {"url": url, "token": token, "header": sys.argv[5] if len(sys.argv) == 6 else "Authorization",
               "path": config.board(board)["restore"]["path"]}
    sys.stdout.write(lj.to_yaml(render(board, device, restore)))
