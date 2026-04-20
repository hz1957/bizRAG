from __future__ import annotations

import uvicorn

from file_service.app.config import settings


def main() -> None:
    cfg = settings()
    uvicorn.run(
        "file_service.app.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
