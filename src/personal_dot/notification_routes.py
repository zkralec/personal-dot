import logging

from fastapi import APIRouter, HTTPException, status

from personal_dot.notification_service import (
    NotificationConfigurationError,
    NotificationError,
    get_notification_service,
)
from personal_dot.schemas import TestNotificationResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/test", response_model=TestNotificationResponse)
def send_test_notification() -> TestNotificationResponse:
    logger.info(
        "Test notification started",
        extra={"event": "notification_test_started"},
    )
    try:
        result = get_notification_service().send_test_notification()
    except NotificationConfigurationError:
        logger.warning(
            "Test notification configuration is incomplete",
            extra={"event": "notification_test_failed"},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="notification provider is not configured",
        ) from None
    except NotificationError:
        logger.warning(
            "Test notification delivery failed",
            extra={"event": "notification_test_failed"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="notification provider rejected or could not deliver the request",
        ) from None
    except Exception:
        logger.error(
            "Unexpected test notification failure",
            extra={"event": "notification_test_failed"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="notification delivery failed",
        ) from None

    logger.info(
        "Test notification sent",
        extra={
            "event": "notification_test_sent",
            "provider": result.provider,
            "provider_request_id": result.provider_request_id,
        },
    )
    return TestNotificationResponse(
        status="sent",
        provider=result.provider,
        provider_request_id=result.provider_request_id,
    )
