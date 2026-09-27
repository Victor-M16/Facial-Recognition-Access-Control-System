import logging

from .db import AccessEvent

log = logging.getLogger(__name__)


class AccessController:
    """Sends lock/unlock to the ESP32 and records every attempt in access_events."""

    def __init__(self, lock_client, session_factory):
        self.lock_client = lock_client
        self.session_factory = session_factory

    def lock(self, name=None, source="remote"):
        return self._send("lock", self.lock_client.lock, name, source)

    def unlock(self, name=None, source="remote"):
        return self._send("unlock", self.lock_client.unlock, name, source)

    def status(self):
        return self.lock_client.status()

    def _send(self, action, command, name, source):
        success = command()
        log.info("%s (%s, %s): %s", action, source, name, "ok" if success else "failed")
        with self.session_factory() as session:
            session.add(AccessEvent(name=name, action=action, source=source, success=success))
            session.commit()
        return success
