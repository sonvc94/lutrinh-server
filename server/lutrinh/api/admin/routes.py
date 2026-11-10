"""Routes, drafts, legs, jobs, publishing, versions and codes (page 03 admin table)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from lutrinh.api.admin import schemas as s
from lutrinh.api.admin import views
from lutrinh.api.deps import AdminDep, DbDep, SettingsDep
from lutrinh.db.models import Code, Draft, Job, RouteVersion
from lutrinh.services import audit, publishing, routes
from lutrinh.services import codes as code_service
from lutrinh.services.errors import not_found

router = APIRouter()

IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _draft_meta(d: Draft) -> dict[str, object]:
    return {
        "revision": d.revision,
        "title": d.body.get("title"),
        "stops": len(d.body.get("stops") or []),
        "legs": len(d.body.get("legs") or []),
    }


def _draft_out(d: Draft, response: Response, jobs: list[Job] | None = None) -> s.DraftOut:
    response.headers["ETag"] = routes.etag(d.revision)
    return s.DraftOut(
        route_id=d.route_id,
        revision=d.revision,
        etag=routes.etag(d.revision),
        updated_at=d.updated_at,
        body=d.body,
        queued_jobs=[j.id for j in jobs or []],
    )


# --- routes ----------------------------------------------------------------------------


@router.get("/routes", response_model=list[s.RouteOut])
def list_routes(
    _: AdminDep,
    db: DbDep,
    status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[s.RouteOut]:
    return [views.summary_out(sm) for sm in routes.list_routes(db, status=status, q=q)]


@router.post("/routes", response_model=s.RouteOut, status_code=201)
def create_route(body: s.RouteCreate, _: AdminDep, db: DbDep) -> s.RouteOut:
    route = routes.create(db, body.title.strip())
    audit.record(db, "route.create", route_id=route.id, after={"title": body.title})
    db.commit()
    return views.route_out(db, route.id)


@router.get("/routes/{route_id}", response_model=s.RouteOut)
def get_route(route_id: str, _: AdminDep, db: DbDep) -> s.RouteOut:
    return views.route_out(db, route_id)


@router.delete("/routes/{route_id}", status_code=204)
def delete_route(
    route_id: str, _: AdminDep, db: DbDep, purge: Annotated[bool, Query()] = False
) -> Response:
    if purge:
        job = routes.purge(db, route_id)
        audit.record(db, "route.purge", route_id=route_id, after={"jobId": job.id})
    else:
        routes.trash(db, route_id)
        audit.record(db, "route.trash", route_id=route_id)
    db.commit()
    return Response(status_code=204)


@router.post("/routes/{route_id}/restore", response_model=s.RouteOut)
def restore_route(route_id: str, _: AdminDep, db: DbDep) -> s.RouteOut:
    routes.restore(db, route_id)
    audit.record(db, "route.restore", route_id=route_id)
    db.commit()
    return views.route_out(db, route_id)


# --- draft and legs --------------------------------------------------------------------


@router.get("/routes/{route_id}/draft", response_model=s.DraftOut)
def get_draft(route_id: str, _: AdminDep, db: DbDep, response: Response) -> s.DraftOut:
    return _draft_out(routes.get_draft(db, route_id), response)


@router.put("/routes/{route_id}/draft", response_model=s.DraftOut)
def put_draft(
    route_id: str,
    body: s.DraftBody,
    _: AdminDep,
    db: DbDep,
    response: Response,
    if_match: IfMatch = None,
) -> s.DraftOut:
    before = _draft_meta(routes.get_draft(db, route_id))
    result = routes.put_draft(db, route_id, body.to_body(), if_match)
    audit.record(
        db, "draft.update", route_id=route_id, before=before, after=_draft_meta(result.draft)
    )
    db.commit()
    return _draft_out(result.draft, response, result.jobs)


@router.post("/routes/{route_id}/legs/{to_stop}/compute", response_model=s.JobRef, status_code=202)
def compute_leg(route_id: str, to_stop: str, _: AdminDep, db: DbDep) -> s.JobRef:
    job = routes.compute_leg(db, route_id, to_stop)
    audit.record(db, "leg.compute", route_id=route_id, target=to_stop, after={"jobId": job.id})
    db.commit()
    return s.JobRef(job_id=job.id)


@router.put("/routes/{route_id}/legs/{to_stop}", response_model=s.DraftOut)
def put_manual_leg(
    route_id: str,
    to_stop: str,
    body: s.ManualLegIn,
    _: AdminDep,
    db: DbDep,
    response: Response,
    if_match: IfMatch = None,
) -> s.DraftOut:
    draft = routes.put_manual_leg(
        db, route_id, to_stop, path=body.path, duration_s=body.duration_s, if_match=if_match
    )
    audit.record(db, "leg.manual", route_id=route_id, target=to_stop, after=_draft_meta(draft))
    db.commit()
    return _draft_out(draft, response)


@router.get("/jobs/{job_id}", response_model=s.JobOut)
def get_job(job_id: int, _: AdminDep, db: DbDep) -> s.JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise not_found("job", job_id)
    return views.job_out(job)


# --- publishing and versions -----------------------------------------------------------


@router.get("/routes/{route_id}/publish", response_model=s.PreflightOut)
def preflight(route_id: str, _: AdminDep, db: DbDep, settings: SettingsDep) -> s.PreflightOut:
    p = publishing.preflight(db, route_id, long_leg_km=settings.long_leg_warn_km)
    return s.PreflightOut(
        next_version=p.version,
        can_publish=not p.blockers,
        blockers=views.problems(p.blockers),
        warnings=views.problems(p.warnings),
        media_bytes=p.media_bytes,
        media_files=p.media_files,
    )


def _published_out(db: DbDep, route_id: str, p: publishing.Published, action: str) -> s.PublishOut:
    audit.record(
        db,
        action,
        route_id=route_id,
        target=f"v{p.version.version}",
        after={
            "version": p.version.version,
            "sha256": p.version.sha256,
            "sourceVersion": p.version.source_version,
            "codeIssued": p.code.code if p.code_issued else None,
        },
    )
    db.commit()
    return s.PublishOut(
        version=views.version_out(p.version),
        code=views.code_out(p.code),
        code_issued=p.code_issued,
        warnings=views.problems(p.warnings),
    )


@router.post("/routes/{route_id}/publish", response_model=s.PublishOut, status_code=201)
def publish(
    route_id: str, body: s.PublishIn, _: AdminDep, db: DbDep, settings: SettingsDep
) -> s.PublishOut:
    p = publishing.publish(
        db,
        route_id,
        long_leg_km=settings.long_leg_warn_km,
        note=body.note,
        code_prefix=body.code_prefix,
    )
    return _published_out(db, route_id, p, "route.publish")


@router.post("/routes/{route_id}/unpublish", response_model=s.RouteOut)
def unpublish(route_id: str, _: AdminDep, db: DbDep) -> s.RouteOut:
    publishing.unpublish(db, route_id)
    audit.record(db, "route.unpublish", route_id=route_id)
    db.commit()
    return views.route_out(db, route_id)


@router.post(
    "/routes/{route_id}/versions/{version}/republish",
    response_model=s.PublishOut,
    status_code=201,
)
def republish(
    route_id: str, version: int, body: s.RepublishIn, _: AdminDep, db: DbDep
) -> s.PublishOut:
    p = publishing.republish(db, route_id, version, note=body.note)
    return _published_out(db, route_id, p, "route.republish")


@router.get("/routes/{route_id}/versions", response_model=list[s.VersionOut])
def list_versions(route_id: str, _: AdminDep, db: DbDep) -> list[s.VersionOut]:
    routes.get(db, route_id)
    rows = db.scalars(
        select(RouteVersion)
        .where(RouteVersion.route_id == route_id)
        .order_by(RouteVersion.version.desc())
    )
    return [views.version_out(v) for v in rows]


# --- codes -----------------------------------------------------------------------------


@router.get("/routes/{route_id}/codes", response_model=list[s.CodeOut])
def list_codes(route_id: str, _: AdminDep, db: DbDep) -> list[s.CodeOut]:
    routes.get(db, route_id)
    rows = db.scalars(
        select(Code).where(Code.route_id == route_id).order_by(Code.created_at.desc())
    )
    return [views.code_out(c) for c in rows]


@router.post("/routes/{route_id}/codes", response_model=s.CodeOut, status_code=201)
def create_code(route_id: str, body: s.CodeCreate, _: AdminDep, db: DbDep) -> s.CodeOut:
    row = code_service.issue(db, route_id, prefix=body.prefix, expires_at=body.expires_at)
    audit.record(db, "code.issue", route_id=route_id, target=row.code)
    db.commit()
    return views.code_out(row)


@router.patch("/codes/{code}", response_model=s.CodeOut)
def patch_code(code: str, body: s.CodePatch, _: AdminDep, db: DbDep) -> s.CodeOut:
    row = code_service.get(db, code)
    before = {"expiresAt": row.expires_at.isoformat() if row.expires_at else None}
    row = code_service.set_expiry(db, code, body.expires_at)
    after = {"expiresAt": row.expires_at.isoformat() if row.expires_at else None}
    audit.record(
        db, "code.expiry", route_id=row.route_id, target=row.code, before=before, after=after
    )
    db.commit()
    return views.code_out(row)


@router.post("/codes/{code}/revoke", response_model=s.RevokeOut)
def revoke_code(code: str, body: s.RevokeIn, _: AdminDep, db: DbDep) -> s.RevokeOut:
    row = code_service.revoke(db, code, reason=body.reason)
    audit.record(
        db, "code.revoke", route_id=row.route_id, target=row.code, after={"reason": body.reason}
    )
    new = None
    if body.reissue:
        new = code_service.issue(db, row.route_id, prefix=body.prefix)
        audit.record(db, "code.issue", route_id=row.route_id, target=new.code)
    db.commit()
    return s.RevokeOut(
        revoked=views.code_out(row), new_code=views.code_out(new) if new is not None else None
    )
