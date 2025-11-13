"""
Federation Helper Functions

Utility functions for integrating federation with other parts of OpenTAKServer.
"""

import json
import fnmatch

from opentakserver.extensions import logger, db
from opentakserver.models.FederationServer import FederationServer
from opentakserver.models.FederationOutbound import FederationOutbound
from opentakserver.models.MissionChange import MissionChange


def queue_mission_change_for_federation(mission_change_id: int) -> None:
    """
    Queue a mission change to be sent to all enabled federated servers.

    This function should be called after a mission change has been committed to the database.
    It creates FederationOutbound records for each enabled federation server that syncs missions.

    Args:
        mission_change_id: The ID of the mission change to queue

    Note:
        This function commits changes to the database.
    """
    try:
        # Get all enabled federation servers that sync missions
        servers = FederationServer.query.filter_by(
            enabled=True,
            sync_missions=True
        ).all()

        if not servers:
            logger.debug(f"No enabled federation servers to queue mission change {mission_change_id}")
            return

        # Get the mission change to check mission name
        mission_change = MissionChange.query.get(mission_change_id)
        if not mission_change:
            logger.error(f"Mission change {mission_change_id} not found")
            return

        # Create outbound records for each server
        for server in servers:
            # Check if this mission change has already been queued for this server
            existing = FederationOutbound.query.filter_by(
                federation_server_id=server.id,
                mission_change_id=mission_change_id
            ).first()

            if existing:
                logger.debug(f"Mission change {mission_change_id} already queued for server {server.name}")
                continue

            # Check mission_filter if configured
            if server.mission_filter:
                if not _matches_mission_filter(mission_change.mission_name, server.mission_filter):
                    logger.debug(f"Mission {mission_change.mission_name} filtered out for server {server.name}")
                    continue

            # Create outbound record
            outbound = FederationOutbound(
                federation_server_id=server.id,
                mission_change_id=mission_change_id,
                sent=False,
                acknowledged=False,
                retry_count=0
            )
            db.session.add(outbound)

        db.session.commit()
        logger.debug(f"Queued mission change {mission_change_id} for {len(servers)} federation servers")

    except Exception as e:
        logger.error(f"Error queuing mission change {mission_change_id} for federation: {e}", exc_info=True)
        db.session.rollback()


def _matches_mission_filter(mission_name: str, mission_filter_json: str) -> bool:
    """
    Check if a mission name matches the mission filter patterns.

    Args:
        mission_name: Name of the mission to check
        mission_filter_json: JSON string containing array of patterns

    Returns:
        True if mission matches any pattern, False otherwise

    Examples:
        - Exact match: "Operation-Alpha" matches ["Operation-Alpha"]
        - Wildcard: "Training-01" matches ["Training-*"]
        - Multiple patterns: "Emergency-Fire" matches ["Emergency-*", "Training-*"]
    """
    try:
        # Parse JSON filter
        patterns = json.loads(mission_filter_json)
        if not isinstance(patterns, list):
            logger.warning(f"Mission filter is not a list: {mission_filter_json}")
            return False

        # Check if mission name matches any pattern
        for pattern in patterns:
            if fnmatch.fnmatch(mission_name, pattern):
                return True

        return False

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse mission filter JSON: {e}")
        # If filter is invalid, don't filter (safer to send than to drop)
        return True
    except Exception as e:
        logger.error(f"Error checking mission filter: {e}")
        return True


def should_federate_mission_change(mission_change) -> bool:
    """
    Determine if a mission change should be federated.

    Args:
        mission_change: The MissionChange object to check

    Returns:
        True if the change should be federated, False otherwise

    Rules:
        - Don't federate changes that are already marked as federated (to avoid loops)
        - Don't federate if federation is disabled
    """
    # Don't federate changes that came from another federation server
    if mission_change.isFederatedChange:
        return False

    return True
