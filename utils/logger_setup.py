"""NEXUS AI - Logger Setup"""
import os
from loguru import logger


def setup_logger():
    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/nexus_ai.log",
        rotation="10 MB",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    )
    logger.add(
        "logs/errors.log",
        rotation="5 MB",
        retention="60 days",
        level="ERROR",
    )
    logger.info("Logger initialized")
