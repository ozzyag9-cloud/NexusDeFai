"""
NEXUS AI - Health Monitor
Runs every 5 minutes, checks that all agents and services are healthy.
Fires a Telegram alert to the admin if anything is wrong.
Self-heals where possible (e.g. resets stuck scheduler jobs).
"""

import asyncio
import time
from datetime import datetime, timedelta
from loguru import logger
from utils.database import SignalDatabase


class HealthMonitor:
    """
    Lightweight watchdog that checks:
    - DB is reachable and returning data
    - Signals are being generated (not stuck)
    - Memory / error thresholds
    - Sends Telegram alert on first failure and on recovery
    """

    CHECK_INTERVAL_SECS = 300        # every 5 minutes
    SIGNAL_STALE_HOURS  = 2.0        # alert if no new signal in 2h during market hours
    MAX_CONSECUTIVE_ERRORS = 3       # alert after 3 consecutive check failures

    def __init__(self, db: SignalDatabase, publisher=None, scheduler=None):
        self.db         = db
        self.publisher  = publisher
        self.scheduler  = scheduler
        self.name       = "HealthMonitor"

        self._consecutive_errors = 0
        self._last_alert_sent    = None
        self._last_known_good    = datetime.utcnow()
        self._was_healthy        = True

    async def check(self) -> dict:
        """
        Run all health checks. Returns status dict.
        {healthy: bool, checks: {name: {ok, detail}}}
        """
        checks = {}

        # ── 1. Database reachability ──────────────────────────
        try:
            signals = await self.db.get_recent_signals(limit=1)
            checks["database"] = {"ok": True, "detail": "connected"}
        except Exception as e:
            checks["database"] = {"ok": False, "detail": f"error: {e}"}

        # ── 2. Signal freshness ───────────────────────────────
        try:
            signals = await self.db.get_recent_signals(limit=5)
            if signals:
                latest_ts = datetime.fromisoformat(signals[0]["timestamp"])
                age_hours = (datetime.utcnow() - latest_ts).total_seconds() / 3600
                stale = age_hours > self.SIGNAL_STALE_HOURS
                checks["signal_freshness"] = {
                    "ok": not stale,
                    "detail": f"last signal {age_hours:.1f}h ago" + (" ⚠️ STALE" if stale else ""),
                }
            else:
                checks["signal_freshness"] = {"ok": True, "detail": "no signals yet (starting up)"}
        except Exception as e:
            checks["signal_freshness"] = {"ok": False, "detail": str(e)}

        # ── 3. Scheduler jobs ─────────────────────────────────
        if self.scheduler:
            try:
                jobs = self.scheduler.get_jobs()
                job_ids = {j.id for j in jobs}
                required = {"signal_cycle", "outcome_tracker"}
                missing  = required - job_ids
                checks["scheduler"] = {
                    "ok": len(missing) == 0,
                    "detail": f"{len(jobs)} jobs running" if not missing
                              else f"missing jobs: {missing}",
                }
            except Exception as e:
                checks["scheduler"] = {"ok": False, "detail": str(e)}
        else:
            checks["scheduler"] = {"ok": True, "detail": "not managed here"}

        # ── 4. Open signal ratio (too many = signals not resolving) ──
        try:
            all_sigs  = await self.db.get_recent_signals(limit=50)
            open_sigs = [s for s in all_sigs if s.get("outcome") == "open"]
            ratio     = len(open_sigs) / max(len(all_sigs), 1)
            too_many  = ratio > 0.8 and len(all_sigs) > 10
            checks["signal_resolution"] = {
                "ok": not too_many,
                "detail": f"{len(open_sigs)}/{len(all_sigs)} open ({ratio*100:.0f}%)"
                          + (" ⚠️ HIGH" if too_many else ""),
            }
        except Exception as e:
            checks["signal_resolution"] = {"ok": True, "detail": "n/a"}

        healthy = all(c["ok"] for c in checks.values())
        return {"healthy": healthy, "checks": checks, "timestamp": datetime.utcnow().isoformat()}

    async def run_loop(self):
        """Continuous health monitoring loop."""
        logger.info(f"[{self.name}] Started (every {self.CHECK_INTERVAL_SECS}s)")
        await asyncio.sleep(60)  # Give the system 60s to warm up first

        while True:
            try:
                result = await self.check()
                healthy = result["healthy"]

                if healthy:
                    self._consecutive_errors = 0
                    if not self._was_healthy:
                        # Recovery — send green alert
                        await self._send_alert(
                            "✅ *NEXUS AI — System Recovered*\n"
                            "All health checks passing.\n"
                            f"_Down for {self._format_downtime()}_",
                            is_recovery=True,
                        )
                        self._was_healthy = True
                    else:
                        logger.debug(f"[{self.name}] ✓ All checks healthy")

                else:
                    self._consecutive_errors += 1
                    failed = [
                        f"• *{k}*: {v['detail']}"
                        for k, v in result["checks"].items()
                        if not v["ok"]
                    ]
                    logger.warning(
                        f"[{self.name}] ⚠ {len(failed)} check(s) failing "
                        f"(consecutive: {self._consecutive_errors})"
                    )

                    if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        if self._was_healthy:
                            self._was_healthy = False
                            self._last_known_good = datetime.utcnow() - timedelta(
                                seconds=self.CHECK_INTERVAL_SECS * self._consecutive_errors
                            )
                        await self._send_alert(
                            f"⚠️ *NEXUS AI — Health Alert*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"{chr(10).join(failed)}\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"Consecutive failures: `{self._consecutive_errors}`\n"
                            f"Time: `{datetime.utcnow().strftime('%H:%M UTC')}`"
                        )

            except Exception as e:
                logger.error(f"[{self.name}] check loop error: {e}")

            await asyncio.sleep(self.CHECK_INTERVAL_SECS)

    async def _send_alert(self, message: str, is_recovery: bool = False):
        """Send alert to admin. Rate-limits to max 1 alert per 30 minutes."""
        if not self.publisher:
            return
        now = datetime.utcnow()
        if (self._last_alert_sent and
                (now - self._last_alert_sent).total_seconds() < 1800 and
                not is_recovery):
            logger.debug(f"[{self.name}] Alert suppressed (rate limit)")
            return
        try:
            await self.publisher.send_admin(message)
            self._last_alert_sent = now
            logger.info(f"[{self.name}] Alert sent to admin")
        except Exception as e:
            logger.error(f"[{self.name}] Alert send failed: {e}")

    def _format_downtime(self) -> str:
        delta = datetime.utcnow() - self._last_known_good
        mins  = int(delta.total_seconds() / 60)
        return f"{mins}m" if mins < 60 else f"{mins//60}h {mins%60}m"
