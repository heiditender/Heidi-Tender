from fastapi import HTTPException, status


def raise_not_implemented() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="TED connector is disabled in SIMAP-only scope.",
    )
