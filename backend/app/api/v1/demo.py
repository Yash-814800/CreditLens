"""Demo persona endpoints (Phase 6, gated by ENABLE_DEMO_ENDPOINTS): lets the
UI (Phase 7's "Load demo persona" menu) and the collision demo (submit P05
then P06) drive the exact same intake/pipeline code path as a real
application, using this repo's own committed data/demo_pack/ fixtures instead
of hand-typed multipart requests. No shortcut through the pipeline: this
builds the same Applicant/Application/Document rows create_application()
would, then hands off to the same background task.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.applications import _run_pipeline_background
from app.api.v1.deps import CurrentUser, require_roles
from app.core.config import settings
from app.core.consent import get_consent_document
from app.core.paths import data_dir
from app.core.security import hmac_sha256_hex, mask_pan, phone_last4
from app.db.models import Applicant, Application, Document
from app.db.session import get_session
from app.schemas.applications import DemoPersonaInfo, DemoPersonaSubmitRequest
from app.services.audit.service import append_event
from app.services.ingestion.storage import build_storage_backend, object_key
from app.services.ingestion.validation import sha256_hex

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
}
_DOC_TYPE_BY_STEM = {
    "gig_payout": "GIG_PAYOUT",
    "utility_bill": "UTILITY_BILL",
    "bank_statement": "BANK_STATEMENT",
}


def _require_demo_enabled() -> None:
    if not settings.enable_demo_endpoints:
        raise HTTPException(404, "demo endpoints are disabled (ENABLE_DEMO_ENDPOINTS=false)")


def _persona_dir(persona_id: str) -> Path:
    pdir = data_dir() / "demo_pack" / persona_id
    if not pdir.exists():
        raise HTTPException(404, f"unknown demo persona {persona_id!r}")
    return pdir


@router.get("/personas", response_model=list[DemoPersonaInfo])
async def list_demo_personas(
    _user: CurrentUser = Depends(require_roles("underwriter", "auditor", "admin")),
) -> list[DemoPersonaInfo]:
    _require_demo_enabled()
    pack_dir = data_dir() / "demo_pack"
    personas = []
    for expected_path in sorted(pack_dir.glob("*/expected.json")):
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        personas.append(
            DemoPersonaInfo(
                persona_id=expected["persona_id"],
                expected_outcome=expected["expected_outcome"],
                notes=expected["notes"],
                docs_present=expected["docs_present"],
            )
        )
    return personas


@router.post("/personas/{persona_id}/submit", status_code=202)
async def submit_demo_persona(
    persona_id: str,
    background_tasks: BackgroundTasks,
    body: DemoPersonaSubmitRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_roles("underwriter", "admin")),
) -> dict[str, str]:
    _require_demo_enabled()
    pdir = _persona_dir(persona_id)
    kyc = json.loads((pdir / "kyc.json").read_text(encoding="utf-8"))

    if body is not None and body.consent_accepted is not None:
        consent_accepted = body.consent_accepted
    else:
        consent_accepted = kyc.get("consent_accepted", kyc.get("consent_given", False))

    if body is not None and body.consent_text_version is not None:
        consent_text_version = body.consent_text_version
    else:
        consent_text_version = kyc.get("consent_text_version")

    active_consent = get_consent_document()
    if not consent_accepted:
        raise HTTPException(422, "consent_accepted must be true to submit a demo persona")
    if consent_text_version != active_consent.version:
        raise HTTPException(
            422,
            f"stale or invalid consent_text_version {consent_text_version!r}; "
            f"active version is {active_consent.version!r}",
        )

    now = datetime.now(UTC)
    applicant = Applicant(
        name=kyc["full_name"],
        phone_hash=hmac_sha256_hex(kyc["phone"], settings.hmac_pepper),
        phone_last4=phone_last4(kyc["phone"]),
        pan_hash=hmac_sha256_hex(kyc["pan"], settings.hmac_pepper),
        pan_masked=mask_pan(kyc["pan"]),
        aadhaar_hash=hmac_sha256_hex(kyc["aadhaar"], settings.hmac_pepper),
        declared_address=kyc.get("declared_address"),
        stated_vocation=kyc.get("stated_vocation"),
        consent_at=now,
        consent_text_version=consent_text_version,
        consent_text_sha256=active_consent.sha256,
    )
    session.add(applicant)
    await session.flush()

    application = Application(
        applicant_id=applicant.id, requested_line_inr=kyc["requested_line_inr"]
    )
    session.add(application)
    await session.flush()

    storage = build_storage_backend(settings)
    docs_submitted = []
    for path in sorted(pdir.iterdir()):
        if path.name in ("kyc.json", "expected.json") or path.name.endswith(".truth.json"):
            continue
        stem = path.stem  # e.g. "utility_bill" from "utility_bill.jpg"
        doc_type = _DOC_TYPE_BY_STEM.get(stem)
        if doc_type is None:
            continue
        data = path.read_bytes()
        mime = _MIME_BY_SUFFIX.get(path.suffix.lower())
        if mime is None:
            continue
        key = object_key(application.id, path.name)
        await storage.put(key, data, mime)
        session.add(
            Document(
                application_id=application.id,
                doc_type=doc_type,
                storage_key=key,
                sha256=sha256_hex(data),
                mime=mime,
                size_bytes=len(data),
            )
        )
        docs_submitted.append(doc_type)

    await session.commit()
    await append_event(
        session,
        event_type="APPLICATION_SUBMITTED",
        actor=user.email,
        application_id=str(application.id),
        applicant_id=str(applicant.id),
        payload={
            "demo_persona": persona_id,
            "docs_submitted": docs_submitted,
            "consent_at": now.isoformat(),
            "consent_text_version": consent_text_version,
            "consent_text_sha256": active_consent.sha256,
        },
    )
    await session.commit()

    background_tasks.add_task(_run_pipeline_background, application.id)
    return {"id": str(application.id), "persona_id": persona_id}
