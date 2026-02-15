"""
Django app configuration for Viassistant
Initializes Bluetooth speaker connection on startup
"""

import logging
import django.apps
import asyncio
import os

logger = logging.getLogger("viassistant.apps")

BLUETOOTH_SPEAKER_NAME = os.getenv("VI_BLUETOOTH_SPEAKER_NAME", "MAP140")


class ViassistantConfig(django.apps.AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "viassistant"

    def ready(self):
        """Initialize Bluetooth speaker on app startup"""
        try:
            from .bluetooth_audio import init_bluetooth_speaker

            # Try to initialize Bluetooth speaker connection
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    init_bluetooth_speaker(BLUETOOTH_SPEAKER_NAME)
                )
                if result:
                    logger.info("[app] Bluetooth speaker initialized: %s", BLUETOOTH_SPEAKER_NAME)
                else:
                    logger.warning("[app] Bluetooth speaker initialization incomplete")
            finally:
                loop.close()
        except Exception as e:
            logger.warning("[app] Bluetooth initialization not critical, continuing: %s", e)
