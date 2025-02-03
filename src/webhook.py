import requests

from config import WEBHOOK_IP
from jobs import Job

active_status: Job | None = None


def push_webhook(update_type: str = "QUEUE", update_state: Job | None = None):
    from builder import BUILD_QUEUE, active_build  # noqa: PLC0415
    from distribution import distribution_queue, upload_status  # noqa: PLC0415

    if update_state is not None:
        global active_status
        active_status = update_state
    requests.post(
        WEBHOOK_IP,
        json={
            "update": {
                "type": update_type,
                "state": update_state.to_json() if update_state else None,
            },
            "status": active_status.status if active_status else None,
            "build": {
                "active": active_build.to_json() if active_build else None,
                "queue": [
                    action.to_json() for action in list(BUILD_QUEUE.queue)
                ],  # allegedly safe (https://stackoverflow.com/a/8196904)
            },
            "test": {
                "activeTests": [
                    {
                        "ip": ip,
                        "locked": False,  # TODO
                        "active": stat.job.to_json() if stat.job else None,
                    }
                    for ip, stat in upload_status.items()
                ],
                "queue": [action.to_json() for action in list(distribution_queue.queue)],
            },
        },
        headers={"content-type": "application/json"},
        timeout=15,
    )
