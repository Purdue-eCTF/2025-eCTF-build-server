import requests


def push_webhook(update_type: str = "QUEUE", update_state: ActionResult = None):
    requests.post(
        WEBHOOK_IP,
        json={
            "update": {
                "type": update_type,
                "state": update_state.to_json() if update_state else None,
            },
            "build": {
                "active": active_build.to_json() if active_build else None,
                "queue": [action.to_json() for action in build_queue],
            },
            "test": {
                "activeTests": [
                    {
                        "ip": ip,
                        "locked": stat.locked,
                        "active": stat.result.to_json() if stat.result else None,
                    }
                    for ip, stat in upload_status.items()
                ],
                "queue": [action.to_json() for action in upload_queue],
            },
        },
        headers={"content-type": "application/json"},
    )
