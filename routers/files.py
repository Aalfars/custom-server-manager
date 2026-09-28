import os
import io
import base64
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, Response
from pydantic import BaseModel

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth
from services.file_manager import (
    list_directory,
    read_file,
    save_file,
    upload_file,
    extract_archive
)

router = APIRouter(prefix="/api/nodes", tags=["files"])

class SaveFileRequest(BaseModel):
    path: str
    content: str

class ExtractArchiveRequest(BaseModel):
    path: str
    destination: Optional[str] = None

@router.get("/{node_id}/files")
async def get_files(node_id: str, path: str = "/root", request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        try:
            return list_directory(path=path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Path not found")
        except NotADirectoryError:
            raise HTTPException(status_code=400, detail="Target path is not a directory")
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "list_files", "path": path})

@router.get("/{node_id}/file-content")
async def get_file_content(node_id: str, path: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            return read_file(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "file_content", "path": path})

@router.post("/{node_id}/file-save")
async def post_file_save(node_id: str, payload: SaveFileRequest, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            res = save_file(payload.path, payload.content)
            log_audit(node_id, "SAVE_FILE", f"Edited {payload.path}")
            return res
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "save_file", "path": payload.path, "content": payload.content})

# File Upload Feature
@router.post("/{node_id}/file-upload")
async def post_file_upload(
    node_id: str,
    request: Request,
    file: UploadFile = File(...),
    target_dir: str = Form("/root")
):
    require_auth(request)
    try:
        content = await file.read()
        filename = file.filename or "uploaded_file"

        if node_id == "local-host":
            res = upload_file(target_dir=target_dir, filename=filename, content=content)
            log_audit(node_id, "FILE_UPLOAD", f"Uploaded {filename} to {target_dir} ({len(content)} bytes)")
            return res
        else:
            agent = connected_agents.get(node_id)
            if not agent:
                raise HTTPException(status_code=404, detail="Agent is offline")

            dest_path = os.path.join(target_dir.rstrip("/"), filename)
            b64_data = base64.b64encode(content).decode("ascii")
            resp = await send_agent_rpc(node_id, {
                "action": "save_binary",
                "path": dest_path,
                "data_b64": b64_data
            }, timeout=60.0)
            log_audit(node_id, "REMOTE_FILE_UPLOAD", f"Uploaded {filename} to {dest_path}")
            return resp
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# File Download Feature
@router.get("/{node_id}/file-download")
async def get_file_download(node_id: str, path: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        target = os.path.abspath(path)
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail="File not found")

        filename = os.path.basename(target)
        log_audit(node_id, "FILE_DOWNLOAD", f"Downloaded {target}")
        return FileResponse(
            path=target,
            filename=filename,
            media_type="application/octet-stream"
        )
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")

        resp = await send_agent_rpc(node_id, {"action": "read_binary", "path": path}, timeout=60.0)
        if not resp.get("success"):
            raise HTTPException(status_code=400, detail=resp.get("error", "Failed to download remote file"))

        b64_data = resp.get("data_b64", "")
        raw_bytes = base64.b64decode(b64_data)
        filename = os.path.basename(path)
        log_audit(node_id, "REMOTE_FILE_DOWNLOAD", f"Downloaded {path}")
        return Response(
            content=raw_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

# Archive Extraction Feature
@router.post("/{node_id}/file-extract")
async def post_file_extract(node_id: str, payload: ExtractArchiveRequest, request: Request):
    require_auth(request)
    archive_path = payload.path.strip()
    dest_dir = payload.destination.strip() if payload.destination else None

    if not archive_path:
        raise HTTPException(status_code=400, detail="Path arsip tidak boleh kosong")

    if node_id == "local-host":
        try:
            res = extract_archive(archive_path, dest_dir)
            log_audit(node_id, "FILE_EXTRACT", f"Extracted {archive_path} to {res['destination']}")
            return res
        except (FileNotFoundError, ValueError) as ve:
            return JSONResponse(status_code=400, content={"success": False, "error": str(ve)})
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")

        resp = await send_agent_rpc(node_id, {
            "action": "file_extract",
            "path": archive_path,
            "destination": dest_dir
        }, timeout=120.0)
        log_audit(node_id, "REMOTE_FILE_EXTRACT", f"Extracted {archive_path}")
        return resp
