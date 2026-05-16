import os, tempfile, zipfile, httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from config import settings
from db import users_col, folders_col, files_col
from models import Folder, VaultFile
from utils import validate_init_data, create_jwt, get_current_user, hash_passcode, verify_passcode
from bot import bot
from aiogram.types import BufferedInputFile

router = APIRouter()
ADMIN_ID = 7728424218

class AuthRequest(BaseModel): initData: str
@router.post("/api/auth")
async def authenticate(req: AuthRequest):
    user_data = validate_init_data(req.initData)
    if not user_data: raise HTTPException(status_code=401)
    tg_id = user_data["id"]
    user_db = await users_col.find_one({"tg_id": tg_id})
    has_passcode = bool(user_db and user_db.get("passcode_hash"))
    return {"token": create_jwt(tg_id, not has_passcode), "has_passcode": has_passcode}

class PasscodeRequest(BaseModel): passcode: str
@router.post("/api/lock/verify")
async def verify_lock(req: PasscodeRequest, user=Depends(get_current_user)):
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    if not user_db or not user_db.get("passcode_hash") or verify_passcode(req.passcode, user_db["passcode_hash"]):
        return {"success": True, "token": create_jwt(user["tg_id"], True)}
    raise HTTPException(status_code=401)

@router.get("/api/user")
async def get_user_info(user=Depends(get_current_user)):
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    return {"storage_used": user_db.get("storage_used", 0), "storage_limit": user_db.get("storage_limit", 50*1024**3)}

@router.get("/api/vault")
async def get_vault(folder_id: Optional[str] = None, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(status_code=403)
    folders = await folders_col.find({"owner_id": user["tg_id"], "parent_id": folder_id}).to_list(None)
    files = await files_col.find({"owner_id": user["tg_id"], "folder_id": folder_id}).to_list(None)
    
    breadcrumbs, current_id = [], folder_id
    while current_id:
        f = await folders_col.find_one({"id": current_id})
        if f: breadcrumbs.insert(0, {"id": f["id"], "name": f["name"]}); current_id = f.get("parent_id")
        else: break
    return {
        "folders": [{"id": f["id"], "name": f["name"], "created_at": f["created_at"]} for f in folders],
        "files": [{"id": f["id"], "name": f["filename"], "mime_type": f["mime_type"], "size": f["size"], "created_at": f["created_at"]} for f in files],
        "breadcrumbs": breadcrumbs
    }

class FolderCreate(BaseModel): name: str; parent_id: Optional[str] = None
@router.post("/api/folders")
async def create_folder(req: FolderCreate, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(403)
    new_folder = Folder(owner_id=user["tg_id"], parent_id=req.parent_id, name=req.name)
    await folders_col.insert_one(new_folder.model_dump())
    return {"success": True}

class RenameReq(BaseModel): name: str
@router.put("/api/rename/{type}/{id}")
async def rename_item(type: str, id: str, req: RenameReq, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(403)
    if type == "file": await files_col.update_one({"id": id, "owner_id": user["tg_id"]}, {"$set": {"filename": req.name}})
    else: await folders_col.update_one({"id": id, "owner_id": user["tg_id"]}, {"$set": {"name": req.name}})
    return {"success": True}

class PasteReq(BaseModel): target_folder: Optional[str] = None; items: List[dict] # {id, type, action: cut/copy}
@router.post("/api/paste")
async def paste_items(req: PasteReq, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(403)
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    
    for item in req.items:
        if item["type"] == "file":
            f = await files_col.find_one({"id": item["id"], "owner_id": user["tg_id"]})
            if not f: continue
            if item["action"] == "cut":
                await files_col.update_one({"id": item["id"]}, {"$set": {"folder_id": req.target_folder}})
            elif item["action"] == "copy":
                if user_db["storage_used"] + f["size"] > user_db["storage_limit"]: continue
                new_f = f.copy(); new_f["id"] = VaultFile().id; new_f["folder_id"] = req.target_folder; new_f.pop("_id")
                await files_col.insert_one(new_f)
                await users_col.update_one({"tg_id": user["tg_id"]}, {"$inc": {"storage_used": f["size"]}})
                user_db["storage_used"] += f["size"]
        elif item["type"] == "folder" and item["action"] == "cut":
            await folders_col.update_one({"id": item["id"], "owner_id": user["tg_id"]}, {"$set": {"parent_id": req.target_folder}})
    return {"success": True}

@router.post("/api/files/upload")
async def upload_file_api(file: UploadFile = File(...), folder_id: Optional[str] = Form(None), user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(403)
    user_db = await users_col.find_one({"tg_id": user["tg_id"]})
    content = await file.read()
    size = len(content)
    
    if size > 40 * 1024 * 1024: raise HTTPException(400, "Too large")
    if user_db.get("storage_used", 0) + size > user_db.get("storage_limit", 50*1024**3): raise HTTPException(400, "Storage full")

    msg = await bot.send_document(chat_id=settings.STORAGE_CHANNEL_ID, document=BufferedInputFile(content, filename=file.filename))
    new_file = VaultFile(owner_id=user["tg_id"], folder_id=folder_id if folder_id != "null" else None, filename=file.filename, mime_type=file.content_type or "application/octet-stream", size=size, file_id=msg.document.file_id, file_unique_id=msg.document.file_unique_id, message_id=msg.message_id)
    await files_col.insert_one(new_file.model_dump())
    await users_col.update_one({"tg_id": user["tg_id"]}, {"$inc": {"storage_used": size}})
    return {"success": True}

class BulkDeleteRequest(BaseModel): file_ids: List[str] = []; folder_ids: List[str] = []
@router.post("/api/bulk/delete")
async def bulk_delete(req: BulkDeleteRequest, user=Depends(get_current_user)):
    if not user["unlocked"]: raise HTTPException(403)
    freed_space = 0
    
    async def get_all_subfolders(f_id, lst):
        sub = await folders_col.find({"parent_id": f_id}).to_list(None)
        for s in sub: lst.append(s["id"]); await get_all_subfolders(s["id"], lst)
        
    all_f_ids = list(req.folder_ids)
    for fid in req.folder_ids: await get_all_subfolders(fid, all_f_ids)
    
    files_to_del = await files_col.find({"owner_id": user["tg_id"], "$or": [{"id": {"$in": req.file_ids}}, {"folder_id": {"$in": all_f_ids}}]}).to_list(None)
    for f in files_to_del:
        freed_space += f["size"]
        try: await bot.delete_message(chat_id=settings.STORAGE_CHANNEL_ID, message_id=f["message_id"])
        except: pass
        
    await files_col.delete_many({"id": {"$in": [f["id"] for f in files_to_del]}})
    await folders_col.delete_many({"id": {"$in": all_f_ids}})
    await users_col.update_one({"tg_id": user["tg_id"]}, {"$inc": {"storage_used": -freed_space}})
    return {"success": True}

@router.get("/api/files/download/{file_id}")
async def download_file(file_id: str, token: str):
    from utils import decode_jwt
    payload = decode_jwt(token)
    if not payload or not payload.get("unlocked"): raise HTTPException(403)
    f = await files_col.find_one({"id": file_id, "owner_id": int(payload["sub"])})
    if not f: raise HTTPException(404)
    tg_file = await bot.get_file(f["file_id"])
    url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{tg_file.file_path}"
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes(): yield chunk
    return StreamingResponse(stream(), media_type=f["mime_type"], headers={"Content-Disposition": f'attachment; filename="{f["filename"]}"'})

# --- ADMIN ROUTES ---
@router.get("/api/admin/data")
async def get_admin_data(user=Depends(get_current_user)):
    if user["tg_id"] != ADMIN_ID: raise HTTPException(403)
    users = await users_col.find({}, {"tg_id": 1, "storage_used": 1, "storage_limit": 1, "username": 1}).to_list(None)
    for u in users: 
        u["_id"] = str(u["_id"])
        # FIX: Ensure old users display 50GB default in Admin Panel
        if "storage_limit" not in u:
            u["storage_limit"] = 50 * 1024 * 1024 * 1024
            
    return {"total_users": len(users), "total_used": sum(u.get("storage_used", 0) for u in users), "users": users}

class GrantReq(BaseModel): tg_id: int; gb: int
@router.post("/api/admin/grant")
async def grant_storage(req: GrantReq, user=Depends(get_current_user)):
    if user["tg_id"] != ADMIN_ID: raise HTTPException(403)
    
    # 1. Find the target user
    target_user = await users_col.find_one({"tg_id": req.tg_id})
    if not target_user: raise HTTPException(404, "User not found")
    
    # 2. FIX: Safely get current limit (Default to 50GB if they are an old user)
    current_limit = target_user.get("storage_limit", 50 * 1024 * 1024 * 1024)
    bytes_to_add = req.gb * 1024 * 1024 * 1024
    new_limit = current_limit + bytes_to_add
    
    # 3. Save the new combined limit
    res = await users_col.update_one({"tg_id": req.tg_id}, {"$set": {"storage_limit": new_limit}})
    
    if res.modified_count or res.matched_count:
        try: await bot.send_message(req.tg_id, f"🎉 <b>Premium Upgrade!</b>\n\nYou have got an extra <b>{req.gb} GB</b> of storage!\nThank you for supporting 💕 @yorifederation", parse_mode="HTML")
        except: pass
        return {"success": True}
        
    raise HTTPException(404, "User not found")
