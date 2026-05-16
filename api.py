from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import zipfile
import io
from config import settings
from db import users_col, folders_col, files_col
from models import Folder, VaultFile
from utils import validate_init_data, create_jwt, get_current_user, hash_passcode, verify_passcode
from bot import bot
from aiogram.types import BufferedInputFile
import httpx

router = APIRouter()

class AuthRequest(BaseModel):
    initData: str

@router.post("/api/auth")
async def authenticate(req: AuthRequest):
    user_data = validate_init_data(req.initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram InitData")
    
    tg_id = user_data["id"]
    user_db = await users_col.find_one({"tg_id": tg_id})
    
    has_passcode = False
    if user_db and user_db.get("passcode_hash"):
        has_passcode = True
        
    token = create_jwt(tg_id, unlocked=not has_passcode)
    return {"token": token, "has_passcode": has_passcode}

class PasscodeRequest(BaseModel):
    passcode: str

@router.post("/api/lock/verify")
async def verify_lock(req: PasscodeRequest, user=Depends(get_current_user)):
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    if not user_db or not user_db.get("passcode_hash"):
        return {"success": True, "token": create_jwt(user["tg_id"], True)}
        
    if verify_passcode(req.passcode, user_db["passcode_hash"]):
        return {"success": True, "token": create_jwt(user["tg_id"], True)}
    raise HTTPException(status_code=401, detail="Invalid passcode")

@router.post("/api/lock/set")
async def set_lock(req: PasscodeRequest, user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
    hashed = hash_passcode(req.passcode) if req.passcode else None
    await users_col.update_one({"tg_id": user["tg_id"]}, {"$set": {"passcode_hash": hashed}})
    return {"success": True}

@router.get("/api/vault")
async def get_vault(folder_id: Optional[str] = None, user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
    
    folders = await folders_col.find({"owner_id": user["tg_id"], "parent_id": folder_id}).to_list(None)
    files = await files_col.find({"owner_id": user["tg_id"], "folder_id": folder_id}).to_list(None)
    
    # Breadcrumbs
    breadcrumbs = []
    current_id = folder_id
    while current_id:
        f = await folders_col.find_one({"id": current_id})
        if f:
            breadcrumbs.insert(0, {"id": f["id"], "name": f["name"]})
            current_id = f.get("parent_id")
        else:
            break
            
    return {
        "folders": [{"id": f["id"], "name": f["name"]} for f in folders],
        "files": [{"id": f["id"], "name": f["filename"], "mime_type": f["mime_type"], "size": f["size"]} for f in files],
        "breadcrumbs": breadcrumbs
    }

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None

@router.post("/api/folders")
async def create_folder(req: FolderCreate, user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
    new_folder = Folder(owner_id=user["tg_id"], parent_id=req.parent_id, name=req.name)
    await folders_col.insert_one(new_folder.model_dump())
    return {"success": True, "id": new_folder.id}

@router.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: str, user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
    
    # Recursive deletion utility
    async def delete_recursive(f_id: str):
        sub_folders = await folders_col.find({"parent_id": f_id}).to_list(None)
        for sf in sub_folders:
            await delete_recursive(sf["id"])
        
        # Delete files in folder (Telegram messages technically stay in channel, but DB drops)
        await files_col.delete_many({"folder_id": f_id})
        await folders_col.delete_one({"id": f_id})

    await delete_recursive(folder_id)
    return {"success": True}

@router.post("/api/files/upload")
async def upload_file_api(file: UploadFile = File(...), folder_id: Optional[str] = Form(None), user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
        
    content = await file.read()
    input_file = BufferedInputFile(content, filename=file.filename)
    
    msg = await bot.send_document(chat_id=settings.STORAGE_CHANNEL_ID, document=input_file)
    
    new_file = VaultFile(
        owner_id=user["tg_id"],
        folder_id=folder_id if folder_id != "null" else None,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size=len(content),
        file_id=msg.document.file_id,
        file_unique_id=msg.document.file_unique_id,
        message_id=msg.message_id
    )
    await files_col.insert_one(new_file.model_dump())
    return {"success": True, "id": new_file.id}

@router.delete("/api/files/{file_id}")
async def delete_file(file_id: str, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(status_code=403)
    file_record = await files_col.find_one({"id": file_id, "owner_id": user["tg_id"]})
    if file_record:
        try:
            await bot.delete_message(chat_id=settings.STORAGE_CHANNEL_ID, message_id=file_record["message_id"])
        except:
            pass # Ignore if too old to delete via Bot API
        await files_col.delete_one({"id": file_id})
    return {"success": True}

@router.get("/api/files/download/{file_id}")
async def download_file(file_id: str, token: str):
    # Authenticate via query param for direct downloads
    from utils import decode_jwt
    payload = decode_jwt(token)
    if not payload or not payload.get("unlocked"):
        raise HTTPException(status_code=403)
        
    file_record = await files_col.find_one({"id": file_id, "owner_id": int(payload["sub"])})
    if not file_record:
        raise HTTPException(status_code=404)
        
    tg_file = await bot.get_file(file_record["file_id"])
    file_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{tg_file.file_path}"
    
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", file_url) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
                    
    return StreamingResponse(
        stream(), 
        media_type=file_record["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{file_record["filename"]}"'}
    )

# ---------- Bulk Download (ZIP) with Limits ----------
class BulkDownloadRequest(BaseModel):
    file_ids: list[str]

MAX_BULK_FILES = 20
MAX_BULK_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

@router.post("/api/files/bulk-download")
async def bulk_download_files(req: BulkDownloadRequest, user=Depends(get_current_user)):
    if not user["unlocked"]:
        raise HTTPException(status_code=403, detail="Vault is locked")
    
    if not req.file_ids:
        raise HTTPException(status_code=400, detail="No file IDs provided")
    
    # Limit number of files
    if len(req.file_ids) > MAX_BULK_FILES:
        raise HTTPException(
            status_code=400, 
            detail=f"Too many files selected. Maximum {MAX_BULK_FILES} files per ZIP download."
        )
    
    # Fetch all file records for the user
    file_records = await files_col.find({
        "id": {"$in": req.file_ids},
        "owner_id": user["tg_id"]
    }).to_list(None)
    
    if not file_records:
        raise HTTPException(status_code=404, detail="No files found")
    
    # Check total size
    total_size = sum(f["size"] for f in file_records)
    if total_size > MAX_BULK_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Total file size ({total_size / (1024*1024):.1f} MB) exceeds limit of 50 MB. Please select fewer or smaller files."
        )
    
    # Create in-memory ZIP
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file_record in file_records:
            try:
                # Get file from Telegram
                tg_file = await bot.get_file(file_record["file_id"])
                file_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{tg_file.file_path}"
                
                # Download file content
                async with httpx.AsyncClient() as client:
                    response = await client.get(file_url)
                    if response.status_code == 200:
                        zip_file.writestr(file_record["filename"], response.content)
                    else:
                        zip_file.writestr(f"ERROR_{file_record['filename']}", f"Failed to download: HTTP {response.status_code}")
            except Exception as e:
                zip_file.writestr(f"ERROR_{file_record['filename']}", f"Download error: {str(e)}")
    
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=vault_export.zip"}
    )
    # Prepare ZIP response
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=vault_export.zip"}
    )

@router.get("/api/share/info")
async def get_share_info(user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(status_code=403)
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    return {"share_token": user_db["share_token"]}
