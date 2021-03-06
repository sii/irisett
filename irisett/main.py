"""Main starting point for the irisett monitoring server.

Read command line options, start all listeners and start up the monitroing.
"""

import time
import argparse
import configparser
import asyncio

from irisett import (
    log,
    stats,
    sql,
)
from irisett.monitor.active import ActiveMonitorManager
from irisett.notify.manager import NotificationManager
from irisett.webapi import webapi


def parse_cmdline() -> argparse.Namespace:
    """Parse commandline options."""
    parser = argparse.ArgumentParser(
        description="Irisett - a small API driven monitoring server."
    )
    parser.add_argument(
        "-c", "--config", type=str, help="config file to use", required=True
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="debug mode, debug logging etc"
    )
    args = parser.parse_args()
    return args


def parse_configfile(filename: str) -> configparser.ConfigParser:
    """Parse the config file."""
    config = configparser.ConfigParser()
    config.read(filename)
    return config


async def mainloop(
    loop: asyncio.AbstractEventLoop,
    config: configparser.ConfigParser,
    dbcon: sql.DBConnection,
    active_monitor_manager: ActiveMonitorManager,
):
    """Perform all setup that requires the event loop and then just wait around forever."""
    await dbcon.initialize()
    await active_monitor_manager.initialize()
    webapi.initialize(
        loop,
        int(config.get("WEBAPI", "port", fallback="10000")),
        config.get("WEBAPI", "username"),
        config.get("WEBAPI", "password"),
        dbcon,
        active_monitor_manager,
    )
    if config.has_section("WEBMGMT"):
        from irisett.webmgmt import webmgmt

        webmgmt.initialize(
            loop,
            int(config.get("WEBMGMT", "port", fallback="11000")),
            config.get("WEBMGMT", "username"),
            config.get("WEBMGMT", "password"),
            dbcon,
            active_monitor_manager,
        )
    active_monitor_manager.start()
    stats.set("global_startup", time.time())
    log.msg("Irisett startup complete")
    while True:
        await asyncio.sleep(10)


def init_database(config: configparser.ConfigParser) -> sql.DBConnection:
    dbcon = None
    if "type" not in config or config["type"] == "mysql":
        import irisett.sql.db_mysql

        dbcon = irisett.sql.db_mysql.DBConnection(
            config["host"], config["username"], config["password"], config["dbname"]
        )
    elif config["type"] == "sqlite":
        import irisett.sql.db_sqlite

        dbcon = irisett.sql.db_sqlite.DBConnection(config["filename"])
    else:
        log.msg("Invalid DB type %s" % (config["type"]))
    return dbcon


# noinspection PyUnresolvedReferences
def main() -> None:
    """Do all setup that doesn't require the event loop, then start it."""
    args = parse_cmdline()
    config = parse_configfile(args.config)
    debug_mode = args.debug or config.getboolean("DEFAULT", "debug", fallback=False)
    log.configure_logging(
        config.get("DEFAULT", "logtype", fallback="stdout"),
        config.get("DEFAULT", "logfile", fallback=""),
        debug_mode,
    )
    if debug_mode:
        log.debug("Debug mode enabled")
    dbcon = init_database(config["DATABASE"])
    if not dbcon:
        return
    notification_cfg = None
    if config.has_section("NOTIFICATIONS"):
        notification_cfg = config["NOTIFICATIONS"]
    notification_manager = NotificationManager(notification_cfg,)
    active_monitor_manager = ActiveMonitorManager(
        dbcon,
        notification_manager,
        int(config.get("ACTIVE-MONITORS", "max-concurrent-jobs", fallback="200")),
        int(config.get("ACTIVE-MONITORS", "default-monitor-interval", fallback="180")),
        int(config.get("ACTIVE-MONITORS", "default-down-threshold", fallback="3")),
        int(config.get("ACTIVE-MONITORS", "result-retention", fallback="0")),
        debug_mode=debug_mode,
    )
    loop = asyncio.get_event_loop()
    loop.run_until_complete(mainloop(loop, config, dbcon, active_monitor_manager))
    loop.close()
